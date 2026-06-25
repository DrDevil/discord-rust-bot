"""Rust+ client wrapper around the ``rustplus`` library.

Responsibilities:
* Build a ``ServerDetails`` and ``RustSocket`` from config.
* Poll ``get_info``/``get_team_info`` on an interval and translate results into
  neutral observations for the event router.
* Subscribe to team-change and raw protobuf pushes.
* Reconnect with exponential backoff and surface unreachability as an
  ``online=False`` observation rather than letting exceptions escape (§7, §13).

Nothing outside this module imports ``rustplus`` types.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

from rustplus import ProtobufEvent, RustSocket, ServerDetails, TeamEvent
from rustplus.events import TeamEventPayload
from rustplus.structs import RustError

from ..events import (
    InfoObservation,
    TeamMemberObservation,
    TeamObservation,
)

logger = logging.getLogger("rustbot.rustplus_client")

InfoCallback = Callable[[InfoObservation], Awaitable[None]]
TeamCallback = Callable[[TeamObservation], Awaitable[None]]
RawCallback = Callable[[bytes], Awaitable[None]]


class RustClient:
    def __init__(
        self,
        *,
        server_id: str,
        ip: str,
        port: int,
        steam_id: int,
        player_token: int,
        poll_interval: float,
        on_info: InfoCallback,
        on_team: TeamCallback,
        on_raw: Optional[RawCallback] = None,
        debug: bool = False,
        base_backoff: float = 5.0,
        max_backoff: float = 120.0,
    ) -> None:
        """Initialize a Rust+ client with connection details and callbacks.
        
        Creates a client that polls the Rust+ API for server info and team roster
        on a fixed interval, with exponential backoff on connection failures.
        Callbacks are invoked as observations are received.
        
        :param server_id: Unique identifier for this server (for logging/routing).
        :param ip: Rust+ server hostname or IP address.
        :param port: Rust+ server port (typically 6500).
        :param steam_id: Your Steam64 ID (for pairing validation).
        :param player_token: Rust+ app player token (obtained from Companion app).
        :param poll_interval: Polling interval in seconds (minimum 5 per CLAUDE.md section 7).
        :param on_info: Async callback invoked when server info is polled/pushed.
        :param on_team: Async callback invoked when team roster is received.
        :param on_raw: Optional async callback for raw protobuf frames (for debugging).
        :param debug: If True, enables Rust+ library debug logging.
        :param base_backoff: Initial backoff duration (seconds) on connection failure.
        :param max_backoff: Maximum backoff duration (seconds); caps exponential growth.
        :return: None (initializes client instance).
        """
        self.server_id = server_id
        self.server_details = ServerDetails(ip, port, steam_id, player_token)
        self.socket = RustSocket(self.server_details, debug=debug)

        self._poll_interval = poll_interval
        self._on_info = on_info
        self._on_team = on_team
        self._on_raw = on_raw
        self._base_backoff = base_backoff
        self._max_backoff = max_backoff

        self._connected = False
        self._events_registered = False
        self._stopped = False
        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None

        # Quiet the library's self-attached DEBUG handler; let it propagate to
        # our structured root handler instead (see logging_setup.setup_logging).
        rp_logger = logging.getLogger("rustplus.py")
        rp_logger.handlers.clear()
        rp_logger.propagate = True

    # ----------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        """Start the Rust+ polling loop as a background task.
        
        Registers event handlers for team and protobuf pushes, then launches
        the polling task. Does not block; the task runs concurrently.
        
        :return: None (starts background task as side effect).
        """
        self._register_events()
        self._task = asyncio.create_task(self._run(), name="rust-poll-loop")

    async def stop(self) -> None:
        """Stop the polling loop and disconnect from the Rust+ server.
        
        Signals the poll loop to stop, cancels the background task, and closes
        the WebSocket connection. Idempotent; safe to call multiple times.
        
        :return: None (stops loop and closes connection as side effect).
        """
        self._stopped = True
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._safe_disconnect()

    # ----------------------------------------------------------------- events
    def _register_events(self) -> None:
        """Register push event handlers with the rustplus library.
        
        Sets up @TeamEvent and @ProtobufEvent decorators to receive team roster
        changes and raw protobuf messages from the Rust+ server. Skips if already
        registered (idempotent).
        
        :return: None (registers handlers as side effect).
        """
        if self._events_registered:
            return

        @TeamEvent(self.server_details)
        async def _on_team_event(payload: TeamEventPayload) -> None:  # noqa: D401
            await self._handle_team_push(payload)

        @ProtobufEvent(self.server_details)
        async def _on_protobuf(data) -> None:  # data: raw bytes/str frame
            await self._handle_raw(data)

        self._events_registered = True

    async def _handle_team_push(self, payload: TeamEventPayload) -> None:
        """Process an incoming team roster change push from Rust+.
        
        Converts the protobuf team_info to a TeamObservation and invokes the
        registered on_team callback. Exceptions are logged but do not crash the
        polling loop (per CLAUDE.md section 13).
        
        :param payload: TeamEvent payload containing team_info from Rust+.
        :return: None (invokes callback as side effect).
        """
        try:
            obs = self._to_team_observation(payload.team_info)
        except Exception:  # noqa: BLE001 - malformed push must not crash us (§7)
            logger.exception(
                "failed to parse team push",
                extra={"server_id": self.server_id, "event_type": "team_push_error"},
            )
            return
        await self._on_team(obs)

    async def _handle_raw(self, data) -> None:
        """Process an incoming raw protobuf push from Rust+.
        
        Converts the data to bytes and invokes the registered on_raw callback
        (if configured). Used for debug logging or advanced protocol handling.
        No-op if on_raw is None.
        
        :param data: Raw protobuf frame data (bytes or string).
        :return: None (invokes callback as side effect if on_raw is set).
        """
        if self._on_raw is None:
            return
        payload = data if isinstance(data, (bytes, bytearray)) else str(data).encode()
        await self._on_raw(bytes(payload))

    # ----------------------------------------------------------------- poll loop
    async def _run(self) -> None:
        """Main polling loop (runs as background task until stop() is called).
        
        Polls get_info and get_team_info on a fixed interval. On successful polls,
        resets the backoff; on failure, exponentially backs off up to max_backoff.
        Cancellation and exceptions do not propagate (loop logs and continues).
        
        :return: None (runs indefinitely; exits only via stop() or cancellation).
        """
        backoff = self._base_backoff
        while not self._stopped:
            ok = await self._poll_cycle()
            if ok:
                backoff = self._base_backoff
                await self._sleep(self._poll_interval)
            else:
                await self._sleep(backoff)
                backoff = min(backoff * 2, self._max_backoff)

    async def _poll_cycle(self) -> bool:
        """Run one poll cycle (get_info, then get_team_info if connected).
        
        Attempts to connect if not already connected. Fetches server info and
        team roster, emits observations to callbacks, handles errors gracefully.
        Returns False on any connectivity failure (triggers backoff in _run).
        Never raises; exceptions are logged. (Per CLAUDE.md section 13.)
        
        :return: True if poll succeeded (info fetched, callbacks invoked); False on connection failure.
        """
        try:
            if not self._connected and not await self._connect():
                await self._emit_offline()
                return False

            info = await self.socket.get_info()
            if isinstance(info, RustError):
                logger.warning(
                    "get_info failed: %s",
                    info.reason,
                    extra={"server_id": self.server_id, "event_type": "poll_error"},
                )
                await self._mark_disconnected()
                await self._emit_offline()
                return False

            await self._on_info(self._to_info_observation(info))

            team = await self.socket.get_team_info()
            if isinstance(team, RustError):
                # Team info can legitimately fail (e.g. not in a team); this does
                # not mean the server is down, so we keep the cycle successful.
                logger.info(
                    "get_team_info unavailable: %s",
                    team.reason,
                    extra={"server_id": self.server_id, "event_type": "team_unavailable"},
                )
            else:
                await self._on_team(self._to_team_observation(team))

            return True
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - never let the poll loop die (§13)
            logger.exception(
                "unexpected error during poll",
                extra={"server_id": self.server_id, "event_type": "poll_exception"},
            )
            await self._mark_disconnected()
            await self._emit_offline()
            return False

    async def _connect(self) -> bool:
        """Attempt to connect to the Rust+ server and validate credentials.
        
        Connects the WebSocket and validates the connection by calling get_info.
        If validation fails (stale pairing, invalid token, etc), disconnects and
        returns False. On success, sets _connected=True and logs connection event.
        
        :return: True if connection and validation succeeded; False otherwise.
        """
        try:
            # Connect the websocket (but don't use the library's get_time wakeup,
            # which doesn't validate the pairing; instead we validate with get_info).
            ok = await self.socket.ws.connect()
            if not ok:
                return False

            # Validate the connection by making an actual API call. This catches
            # invalid credentials or stale pairings early (not_found errors).
            info = await self.socket.get_info()
            if isinstance(info, RustError):
                logger.warning(
                    "initial get_info after connect failed: %s",
                    info.reason,
                    extra={"server_id": self.server_id, "event_type": "connect_validation_error"},
                )
                await self.socket.ws.disconnect()
                return False

            self._connected = True
            logger.info(
                "connected to rust server",
                extra={"server_id": self.server_id, "event_type": "connected"},
            )
            return True

        except Exception:  # noqa: BLE001 - connect can raise on network errors
            logger.exception(
                "connect raised",
                extra={"server_id": self.server_id, "event_type": "connect_error"},
            )
            return False

    async def _mark_disconnected(self) -> None:
        """Mark the client as disconnected and close the WebSocket.
        
        :return: None (updates connection state and closes socket as side effect).
        """
        self._connected = False
        await self._safe_disconnect()

    async def _safe_disconnect(self) -> None:
        """Safely disconnect from Rust+ server, suppressing any exceptions.
        
        :return: None (closes WebSocket as side effect; exceptions logged but ignored).
        """
        try:
            await self.socket.disconnect()
        except Exception:  # noqa: BLE001
            logger.debug("disconnect raised (ignored)")

    async def _emit_offline(self) -> None:
        """Emit an offline observation to notify the router of disconnection.
        
        :return: None (invokes on_info callback with online=False as side effect).
        """
        await self._on_info(InfoObservation(server_id=self.server_id, online=False))

    async def _sleep(self, seconds: float) -> None:
        """Sleep for a duration that can be interrupted by stop() being called.
        
        Allows graceful shutdown: if stop() is called while sleeping, wakes immediately
        instead of waiting the full duration.
        
        :param seconds: Number of seconds to sleep.
        :return: None (sleeps or wakes early as side effect).
        """
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    # ----------------------------------------------------------------- mapping
    def _to_info_observation(self, info) -> InfoObservation:
        """Convert a Rust+ Info protobuf message to an InfoObservation.
        
        Defensively extracts fields using getattr() with None defaults to handle
        the unofficial Rust+ protocol gracefully (CLAUDE.md section 7). Unknown or missing
        fields become None in the observation.
        
        :param info: Rust+ Info protobuf message (structure may vary).
        :return: InfoObservation with extracted fields (or None for missing data).
        """
        # Defensive attribute access — the protocol is unofficial (§7).
        wipe_time = getattr(info, "wipe_time", None) or None
        return InfoObservation(
            server_id=self.server_id,
            online=True,
            name=getattr(info, "name", None),
            players=getattr(info, "players", None),
            max_players=getattr(info, "max_players", None),
            queued_players=getattr(info, "queued_players", None),
            seed=getattr(info, "seed", None),
            size=getattr(info, "size", None),
            wipe_time=wipe_time,
        )

    def _to_team_observation(self, team_info) -> TeamObservation:
        """Convert a Rust+ TeamInfo protobuf message to a TeamObservation.
        
        Defensively extracts the members list and converts each member to a
        TeamMemberObservation with safe type conversions (CLAUDE.md section 7).
        Missing or None members list is treated as empty roster.
        
        :param team_info: Rust+ TeamInfo protobuf message (structure may vary).
        :return: TeamObservation with parsed member list (empty if none found).
        """
        members = []
        for member in getattr(team_info, "members", []) or []:
            members.append(
                TeamMemberObservation(
                    steam_id=int(getattr(member, "steam_id", 0)),
                    name=str(getattr(member, "name", "")),
                    is_online=bool(getattr(member, "is_online", False)),
                    is_alive=bool(getattr(member, "is_alive", True)),
                )
            )
        return TeamObservation(server_id=self.server_id, members=tuple(members))
