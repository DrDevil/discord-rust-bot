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
        self.state = state
        self._repo = repository
        self._now = now_factory
        self._subscribers: List[Subscriber] = []

    def subscribe(self, callback: Subscriber) -> None:
        self._subscribers.append(callback)

    async def on_info(self, obs: InfoObservation) -> None:
        events = compute_info_events(self.state, obs, self._now())
        self.state.apply_info(obs)
        await self._persist()
        await self._publish(events)

    async def on_team(self, obs: TeamObservation) -> None:
        events = compute_team_events(self.state, obs, self._now())
        self.state.apply_team(obs)
        await self._persist()
        await self._publish(events)

    async def on_raw(self, data: bytes) -> None:
        # Raw protobuf is only of interest while debugging the protocol (§7/§10).
        logger.debug(
            "raw protobuf frame received (%d bytes)",
            len(data),
            extra={"server_id": self.state.server_id, "event_type": "raw_protobuf"},
        )

    async def _persist(self) -> None:
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
    """Build a ``ServerState`` from a persisted record (or a fresh one)."""
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
