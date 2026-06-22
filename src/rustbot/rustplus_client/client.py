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
        self._register_events()
        self._task = asyncio.create_task(self._run(), name="rust-poll-loop")

    async def stop(self) -> None:
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
        if self._on_raw is None:
            return
        payload = data if isinstance(data, (bytes, bytearray)) else str(data).encode()
        await self._on_raw(bytes(payload))

    # ----------------------------------------------------------------- poll loop
    async def _run(self) -> None:
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
        """Run one poll. Returns False on connectivity failure (triggers backoff)."""
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
        self._connected = False
        await self._safe_disconnect()

    async def _safe_disconnect(self) -> None:
        try:
            await self.socket.disconnect()
        except Exception:  # noqa: BLE001
            logger.debug("disconnect raised (ignored)")

    async def _emit_offline(self) -> None:
        await self._on_info(InfoObservation(server_id=self.server_id, online=False))

    async def _sleep(self, seconds: float) -> None:
        """Sleep that wakes immediately when stop() is called."""
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    # ----------------------------------------------------------------- mapping
    def _to_info_observation(self, info) -> InfoObservation:
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
