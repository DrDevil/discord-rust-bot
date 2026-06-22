"""Current-state tracking and pure change-detection (diffing).

``ServerState`` holds the last known status for one server. The ``compute_*``
functions are pure: given a state, an observation, and a timestamp, they return
the list of events implied by the change *without* mutating anything. The router
calls ``compute_*`` first, then ``apply_*`` to advance the state. Keeping the
diff pure makes the alerting rules trivially unit-testable (CLAUDE.md §13).

Baseline rule (avoid startup alert storms): the very first observation of a kind
establishes a silent baseline. Only subsequent transitions emit events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from ..events import (
    BaseEvent,
    InfoObservation,
    ServerStatusChanged,
    TeamObservation,
    TeamMemberStatusChanged,
    WipeDetected,
)


@dataclass
class ServerState:
    """Mutable last-known state for a single server."""

    server_id: str

    # Server status
    online: Optional[bool] = None
    wipe_time: Optional[int] = None
    last_info: Optional[InfoObservation] = None

    # Team roster: steam_id -> is_online, plus names for display
    members: Dict[int, bool] = field(default_factory=dict)
    member_names: Dict[int, str] = field(default_factory=dict)
    last_team: Optional[TeamObservation] = None
    team_seeded: bool = False

    # ----------------------------------------------------------------- apply
    def apply_info(self, obs: InfoObservation) -> None:
        self.online = obs.online
        if obs.wipe_time:
            self.wipe_time = obs.wipe_time
        if obs.online:
            # Only keep details from a successful poll; a failed poll carries none.
            self.last_info = obs

    def apply_team(self, obs: TeamObservation) -> None:
        for member in obs.members:
            self.members[member.steam_id] = member.is_online
            self.member_names[member.steam_id] = member.name
        self.last_team = obs
        self.team_seeded = True


def compute_info_events(
    state: ServerState, obs: InfoObservation, now: datetime
) -> List[BaseEvent]:
    """Events implied by a new server-status reading."""
    events: List[BaseEvent] = []

    if obs.online:
        # Online transition: only alert when we previously *knew* it was down.
        if state.online is False:
            events.append(
                ServerStatusChanged(server_id=state.server_id, timestamp=now, online=True)
            )
        # Wipe detection: alert only when a previously known wipe time changes.
        if obs.wipe_time and state.wipe_time is not None and obs.wipe_time != state.wipe_time:
            events.append(
                WipeDetected(
                    server_id=state.server_id, timestamp=now, wipe_time=obs.wipe_time
                )
            )
    else:
        # Offline transition: only alert when we previously knew it was up.
        if state.online is True:
            events.append(
                ServerStatusChanged(
                    server_id=state.server_id, timestamp=now, online=False
                )
            )

    return events


def compute_team_events(
    state: ServerState, obs: TeamObservation, now: datetime
) -> List[BaseEvent]:
    """Events implied by a new team-roster reading."""
    if not state.team_seeded:
        # First roster establishes the baseline silently.
        return []

    events: List[BaseEvent] = []
    for member in obs.members:
        previous = state.members.get(member.steam_id)
        if previous is None:
            # Newly seen member after baseline: alert if they are online.
            if member.is_online:
                events.append(
                    TeamMemberStatusChanged(
                        server_id=state.server_id,
                        timestamp=now,
                        steam_id=member.steam_id,
                        name=member.name,
                        online=True,
                    )
                )
        elif previous != member.is_online:
            events.append(
                TeamMemberStatusChanged(
                    server_id=state.server_id,
                    timestamp=now,
                    steam_id=member.steam_id,
                    name=member.name,
                    online=member.is_online,
                )
            )

    return events
