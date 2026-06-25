"""Event router.

Receives neutral observations from the Rust+ client, diffs them against the
in-memory ``ServerState`` using the pure functions in ``domain.state``, persists
the new state, and publishes resulting events to subscribers (the alert engine).

Subscribers are async callables. One failing subscriber must not stop the others
or crash the poll loop (CLAUDE.md §13 — fail safely).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable, List

from ..domain.state import (
    ServerState,
    compute_info_events,
    compute_team_events,
)
from ..events import BaseEvent, InfoObservation, TeamObservation
from ..persistence.base import Repository, ServerStateRecord

logger = logging.getLogger("rustbot.event_router")

Subscriber = Callable[[BaseEvent], Awaitable[None]]


class EventRouter:
    def __init__(
        self,
        state: ServerState,
        repository: Repository,
        *,
        now_factory: Callable[[], datetime] = lambda: datetime.now(tz=timezone.utc),
    ) -> None:
        """Initialize the event router with state and persistence.
        
        :param state: Initial ServerState (typically restored from DB).
        :param repository: Repository for persisting state after each observation.
        :param now_factory: Callable that returns current UTC datetime; defaults to datetime.now().
        :return: None (initializes router instance).
        """
        self.state = state
        self._repo = repository
        self._now = now_factory
        self._subscribers: List[Subscriber] = []

    def subscribe(self, callback: Subscriber) -> None:
        """Register a subscriber callback for all emitted events.
        
        Callbacks are invoked for each BaseEvent produced by the router.
        If a callback raises, it is logged but does not affect other callbacks
        or stop the polling loop (CLAUDE.md 13).
        
        :param callback: Async callable taking a BaseEvent; invoked via await.
        :return: None (registers callback for later invocation).
        """
        self._subscribers.append(callback)

    async def on_info(self, obs: InfoObservation) -> None:
        """Process a server-info observation.
        
        Diffs observation against current state to detect changes, updates state,
        persists to DB, and publishes resulting events to subscribers.
        
        :param obs: InfoObservation from Rust+ client (poll or error).
        :return: None (updates state, persists, and publishes events).
        """
        events = compute_info_events(self.state, obs, self._now())
        self.state.apply_info(obs)
        await self._persist()
        await self._publish(events)

    async def on_team(self, obs: TeamObservation) -> None:
        """Process a team-roster observation.
        
        Diffs observation against current state to detect member status changes,
        updates state, persists to DB, and publishes resulting events to subscribers.
        
        :param obs: TeamObservation from Rust+ client (poll or push).
        :return: None (updates state, persists, and publishes events).
        """
        events = compute_team_events(self.state, obs, self._now())
        self.state.apply_team(obs)
        await self._persist()
        await self._publish(events)

    async def on_raw(self, data: bytes) -> None:
        """Process a raw protobuf frame (for debugging).
        
        Logs the raw frame at DEBUG level. Only useful for protocol troubleshooting
        when debug_protobuf is enabled (CLAUDE.md 7, 10).
        
        :param data: Raw protobuf frame bytes from Rust+ server.
        :return: None (logs at DEBUG level only).
        """
        # Raw protobuf is only of interest while debugging the protocol (§7/§10).
        logger.debug(
            "raw protobuf frame received (%d bytes)",
            len(data),
            extra={"server_id": self.state.server_id, "event_type": "raw_protobuf"},
        )

    async def _persist(self) -> None:
        """Persist current state to the repository.
        
        Converts ServerState to a ServerStateRecord and saves it. Exceptions are
        logged but not raised (persistence must never crash the polling loop).
        
        :return: None (saves to repository as side effect).
        """
        record = ServerStateRecord(
            server_id=self.state.server_id,
            online=self.state.online,
            wipe_time=self.state.wipe_time,
            members=dict(self.state.members),
            member_names=dict(self.state.member_names),
        )
        try:
            await self._repo.save_server_state(record)
        except Exception:  # noqa: BLE001 - persistence must never crash polling
            logger.exception(
                "failed to persist server state",
                extra={"server_id": self.state.server_id, "event_type": "persist_error"},
            )

    async def _publish(self, events: List[BaseEvent]) -> None:
        """Publish events to all registered subscribers.
        
        Logs each event, then invokes each subscriber callback. If a subscriber
        raises, the exception is logged and remaining subscribers are still called.
        (Per CLAUDE.md section 13.)
        
        :param events: List of BaseEvent objects to publish.
        :return: None (invokes subscribers as side effect; exceptions logged not raised).
        """
        for event in events:
            logger.info(
                "event: %s",
                event.event_type.value,
                extra={
                    "server_id": event.server_id,
                    "event_type": event.event_type.value,
                },
            )
            for subscriber in self._subscribers:
                try:
                    await subscriber(event)
                except Exception:  # noqa: BLE001 - isolate subscriber failures
                    logger.exception(
                        "subscriber failed for event %s",
                        event.event_type.value,
                        extra={
                            "server_id": event.server_id,
                            "event_type": event.event_type.value,
                        },
                    )


def restore_state(record: ServerStateRecord | None, server_id: str) -> ServerState:
    """Build a ServerState from a persisted record (or a fresh one).
    
    If record is None, returns a blank ServerState. If record exists, reconstructs
    state including member roster. Sets team_seeded=True if there was any roster
    persisted (so the bot resumes emitting member status events immediately after
    restart, without waiting for the first new roster observation)."
    
    :param record: Persisted ServerStateRecord from the repository (or None).
    :param server_id: The server ID to associate with the state.
    :return: Reconstructed or blank ServerState.
    """
    if record is None:
        return ServerState(server_id=server_id)

    state = ServerState(
        server_id=server_id,
        online=record.online,
        wipe_time=record.wipe_time,
        members=dict(record.members),
        member_names=dict(record.member_names),
    )
    # If we persisted any roster before, treat the baseline as established so we
    # resume emitting member transitions immediately after a restart.
    state.team_seeded = bool(record.members)
    return state
