"""Router integration: observations -> events -> subscribers, with persistence."""

from datetime import datetime, timezone

import pytest

from rustbot.domain.state import ServerState
from rustbot.event_router.router import EventRouter, restore_state
from rustbot.events import (
    InfoObservation,
    ServerStatusChanged,
    TeamMemberObservation,
    TeamObservation,
)
from rustbot.persistence.base import ServerStateRecord

NOW = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
SID = "1.2.3.4:28082"


class FakeRepo:
    def __init__(self):
        self.saved = []

    async def save_server_state(self, record):
        self.saved.append(record)

    # Unused by these tests but part of the interface contract.
    async def connect(self): ...
    async def close(self): ...
    async def upsert_server(self, *a, **k): ...
    async def get_encrypted_player_token(self, server_id): ...
    async def load_server_state(self, server_id): ...


def _router():
    repo = FakeRepo()
    state = ServerState(server_id=SID)
    router = EventRouter(state=state, repository=repo, now_factory=lambda: NOW)
    received = []
    router.subscribe(lambda e: _collect(received, e))
    return router, repo, received


async def _collect(bucket, event):
    bucket.append(event)


@pytest.mark.asyncio
async def test_offline_transition_publishes_and_persists():
    """Verify offline transitions both fire events AND persist state.
    
    Ensures the event pipeline integrates: observation -> event -> subscriber,
    and that state changes are persisted for restart recovery.
    """
    router, repo, received = _router()
    await router.on_info(InfoObservation(server_id=SID, online=True))  # baseline
    await router.on_info(InfoObservation(server_id=SID, online=False))

    assert len(received) == 1
    assert isinstance(received[0], ServerStatusChanged)
    assert received[0].online is False
    # State persisted after each observation.
    assert repo.saved[-1].online is False


@pytest.mark.asyncio
async def test_subscriber_exception_does_not_break_router():
    """Verify that a failing subscriber does not crash the router or other subscribers.
    
    Ensures isolation: one subscriber raising an exception doesn't prevent
    the router from processing further events.
    """
    router, repo, _ = _router()

    async def boom(_event):
        raise RuntimeError("subscriber failure")

    router.subscribe(boom)
    await router.on_info(InfoObservation(server_id=SID, online=True))
    # Triggers an event; boom raises but must be swallowed.
    await router.on_info(InfoObservation(server_id=SID, online=False))
    # If we got here without raising, isolation worked.


@pytest.mark.asyncio
async def test_team_push_then_transition():
    """Verify team roster observations: baseline is silent, then transitions fire events.
    
    Ensures team member status changes trigger alerts after the initial roster
    is learned (no spam on startup).
    """
    router, _, received = _router()
    base = TeamObservation(
        server_id=SID,
        members=(TeamMemberObservation(steam_id=1, name="Alice", is_online=False),),
    )
    await router.on_team(base)  # baseline, silent
    assert received == []

    await router.on_team(
        TeamObservation(
            server_id=SID,
            members=(TeamMemberObservation(steam_id=1, name="Alice", is_online=True),),
        )
    )
    assert len(received) == 1
    assert received[0].online is True


def test_restore_state_marks_baseline_when_roster_present():
    """Verify restore_state sets team_seeded=True when persisted roster exists.
    
    Ensures the bot resumes normal alert behavior immediately after restart
    without waiting for a new roster observation.
    """
    record = ServerStateRecord(
        server_id=SID,
        online=True,
        wipe_time=123,
        members={1: True},
        member_names={1: "Alice"},
    )
    state = restore_state(record, SID)
    assert state.team_seeded is True
    assert state.online is True
    assert state.wipe_time == 123


def test_restore_state_fresh_when_no_record():
    """Verify restore_state returns blank state when no persisted record exists.
    
    Ensures first-run (no database) starts with a clean slate.
    """
    state = restore_state(None, SID)
    assert state.team_seeded is False
    assert state.online is None
