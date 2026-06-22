"""The internal event vocabulary shared between layers.

Two kinds of value object live here, deliberately separated:

* **Observations** — neutral readings produced by the Rust+ client layer from a
  poll or a push. They contain no opinion about whether anything *changed*.
* **Events** — state-change facts produced by the event router after diffing an
  observation against the last known state. These are what the domain layer
  turns into alerts.

Keeping both library-agnostic means nothing outside ``rustplus_client`` imports
the third-party ``rustplus`` types (CLAUDE.md §4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Tuple


# --------------------------------------------------------------------------- #
# Observations (client -> router)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class InfoObservation:
    """A single reading of server status (from ``get_info`` or a failed poll)."""

    server_id: str
    online: bool
    name: str | None = None
    players: int | None = None
    max_players: int | None = None
    queued_players: int | None = None
    seed: int | None = None
    size: int | None = None
    wipe_time: int | None = None


@dataclass(frozen=True)
class TeamMemberObservation:
    steam_id: int
    name: str
    is_online: bool
    is_alive: bool = True


@dataclass(frozen=True)
class TeamObservation:
    """A single reading of the team roster (from ``get_team_info`` or a push)."""

    server_id: str
    members: Tuple[TeamMemberObservation, ...] = ()


# --------------------------------------------------------------------------- #
# Events (router -> domain)
# --------------------------------------------------------------------------- #
class EventType(str, Enum):
    SERVER_ONLINE = "server_online"
    SERVER_OFFLINE = "server_offline"
    WIPE_DETECTED = "wipe_detected"
    TEAM_MEMBER_ONLINE = "team_member_online"
    TEAM_MEMBER_OFFLINE = "team_member_offline"


@dataclass(frozen=True)
class BaseEvent:
    server_id: str
    timestamp: datetime

    @property
    def event_type(self) -> EventType:  # pragma: no cover - overridden
        raise NotImplementedError


@dataclass(frozen=True)
class ServerStatusChanged(BaseEvent):
    online: bool = True

    @property
    def event_type(self) -> EventType:
        return EventType.SERVER_ONLINE if self.online else EventType.SERVER_OFFLINE


@dataclass(frozen=True)
class WipeDetected(BaseEvent):
    wipe_time: int = 0

    @property
    def event_type(self) -> EventType:
        return EventType.WIPE_DETECTED


@dataclass(frozen=True)
class TeamMemberStatusChanged(BaseEvent):
    steam_id: int = 0
    name: str = ""
    online: bool = True

    @property
    def event_type(self) -> EventType:
        return (
            EventType.TEAM_MEMBER_ONLINE
            if self.online
            else EventType.TEAM_MEMBER_OFFLINE
        )
