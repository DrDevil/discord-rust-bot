"""Pure diffing rules: baseline-then-transition, no duplicate alerts."""

from datetime import datetime, timezone

from rustbot.domain.state import (
    ServerState,
    compute_info_events,
    compute_team_events,
)
from rustbot.events import (
    InfoObservation,
    ServerStatusChanged,
    TeamMemberObservation,
    TeamMemberStatusChanged,
    TeamObservation,
    WipeDetected,
)

NOW = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
SID = "1.2.3.4:28082"


def _info(online=True, wipe_time=None):
    return InfoObservation(server_id=SID, online=online, wipe_time=wipe_time)


def _apply(state, obs):
    events = compute_info_events(state, obs, NOW)
    state.apply_info(obs)
    return events


def test_first_online_observation_is_silent_baseline():
    """Verify first server online observation establishes silent baseline (no alert).
    
    Ensures the bot doesn't fire a 'server online' alert on first startup.
    Subsequent offline/online transitions will fire alerts normally.
    """
    state = ServerState(server_id=SID)
    assert _apply(state, _info(online=True)) == []
    assert state.online is True


def test_online_to_offline_emits_once():
    """Verify offline transition fires exactly once (no duplicates on repeated polls).
    
    Prevents alert spam when the server is offline and being polled repeatedly.
    """
    state = ServerState(server_id=SID)
    _apply(state, _info(online=True))
    events = _apply(state, _info(online=False))
    assert len(events) == 1
    assert isinstance(events[0], ServerStatusChanged)
    assert events[0].online is False
    # Polling offline again must not re-alert.
    assert _apply(state, _info(online=False)) == []


def test_offline_to_online_emits_recovery():
    """Verify server recovery (offline -> online) fires a status alert.
    
    Players should be notified when a down server comes back online.
    """
    state = ServerState(server_id=SID, online=False)
    events = _apply(state, _info(online=True))
    assert len(events) == 1
    assert isinstance(events[0], ServerStatusChanged)
    assert events[0].online is True


def test_wipe_first_seen_is_silent_then_change_alerts():
    """Verify wipe time: first observation is silent, then changes trigger alert.
    
    Prevents a 'wipe detected' alert on every server restart.
    Only new/changed wipe times trigger alerts.
    """
    state = ServerState(server_id=SID)
    # First time we learn the wipe time: baseline, no alert.
    assert _apply(state, _info(online=True, wipe_time=1000)) == []
    assert state.wipe_time == 1000
    # Same wipe time: no alert.
    assert _apply(state, _info(online=True, wipe_time=1000)) == []
    # New wipe time: alert.
    events = _apply(state, _info(online=True, wipe_time=2000))
    assert len(events) == 1
    assert isinstance(events[0], WipeDetected)
    assert events[0].wipe_time == 2000


def _team(*members):
    return TeamObservation(
        server_id=SID,
        members=tuple(
            TeamMemberObservation(steam_id=sid, name=name, is_online=online)
            for sid, name, online in members
        ),
    )


def _apply_team(state, obs):
    events = compute_team_events(state, obs, NOW)
    state.apply_team(obs)
    return events


def test_team_baseline_is_silent():
    """Verify first team roster observation establishes silent baseline (no alerts).
    
    Prevents teammate 'online' alerts on first startup or when initially learning
    the team roster.
    """
    state = ServerState(server_id=SID)
    events = _apply_team(state, _team((1, "Alice", True), (2, "Bob", False)))
    assert events == []
    assert state.team_seeded is True


def test_team_member_status_transition_emits():
    """Verify team member status changes (online <-> offline) fire alerts.
    
    After baseline is established, any teammate status change should fire an alert.
    """
    state = ServerState(server_id=SID)
    _apply_team(state, _team((1, "Alice", False)))
    events = _apply_team(state, _team((1, "Alice", True)))
    assert len(events) == 1
    assert isinstance(events[0], TeamMemberStatusChanged)
    assert events[0].steam_id == 1
    assert events[0].online is True


def test_team_no_change_is_silent():
    """Verify that identical team roster observations don't fire duplicate alerts.
    
    Prevents alert spam when the same roster is polled repeatedly without changes.
    """
    state = ServerState(server_id=SID)
    _apply_team(state, _team((1, "Alice", True)))
    assert _apply_team(state, _team((1, "Alice", True))) == []


def test_new_member_after_baseline_alerts_when_online():
    """Verify that newly discovered team members trigger alerts when online.
    
    Ensures players are notified when a new teammate appears in the roster and is online.
    """
    state = ServerState(server_id=SID)
    _apply_team(state, _team((1, "Alice", True)))
    events = _apply_team(state, _team((1, "Alice", True), (2, "Bob", True)))
    assert len(events) == 1
    assert events[0].steam_id == 2
    assert events[0].online is True
