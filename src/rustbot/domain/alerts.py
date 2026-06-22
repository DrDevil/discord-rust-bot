"""Alert rules: turn state-change events into neutral alert payloads.

The domain decides *what* to notify and with which severity; it does not know
about Discord. It emits a plain ``Alert`` value object to an ``AlertSink``, which
the Discord layer implements (rendering the embed and sending it). This keeps the
domain free of any discord.py import (CLAUDE.md §4).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import List, Protocol, Tuple

from ..events import (
    BaseEvent,
    ServerStatusChanged,
    TeamMemberStatusChanged,
    WipeDetected,
)

logger = logging.getLogger("rustbot.domain.alerts")


class AlertLevel(str, Enum):
    GOOD = "good"
    INFO = "info"
    WARNING = "warning"


@dataclass(frozen=True)
class Alert:
    """A neutral, render-agnostic alert payload."""

    title: str
    description: str
    level: AlertLevel
    server_id: str
    timestamp: datetime
    fields: Tuple[Tuple[str, str], ...] = field(default_factory=tuple)


class AlertSink(Protocol):
    """Anything that can deliver an alert (implemented by the Discord layer)."""

    async def send_alert(self, alert: Alert) -> None: ...


def _format_epoch(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


class AlertEngine:
    """Renders events to alerts and forwards them to a sink."""

    def __init__(self, sink: AlertSink) -> None:
        self._sink = sink

    async def handle_event(self, event: BaseEvent) -> None:
        alert = self.render(event)
        if alert is None:
            return
        logger.info(
            "dispatching alert",
            extra={"server_id": event.server_id, "event_type": event.event_type.value},
        )
        await self._sink.send_alert(alert)

    @staticmethod
    def render(event: BaseEvent) -> "Alert | None":
        if isinstance(event, ServerStatusChanged):
            if event.online:
                return Alert(
                    title="🟢 Server Online",
                    description="The Rust server is reachable again.",
                    level=AlertLevel.GOOD,
                    server_id=event.server_id,
                    timestamp=event.timestamp,
                )
            return Alert(
                title="🔴 Server Offline",
                description="The Rust server is unreachable.",
                level=AlertLevel.WARNING,
                server_id=event.server_id,
                timestamp=event.timestamp,
            )

        if isinstance(event, WipeDetected):
            return Alert(
                title="🧹 Wipe Detected",
                description=f"A new wipe was detected ({_format_epoch(event.wipe_time)}).",
                level=AlertLevel.WARNING,
                server_id=event.server_id,
                timestamp=event.timestamp,
                fields=(("Wipe time", _format_epoch(event.wipe_time)),),
            )

        if isinstance(event, TeamMemberStatusChanged):
            verb = "came online" if event.online else "went offline"
            emoji = "🟢" if event.online else "⚪"
            return Alert(
                title=f"{emoji} Teammate {verb}",
                # The name is untrusted (set by a player); the Discord layer
                # sanitises and disables mentions before rendering.
                description=f"{event.name} {verb}.",
                level=AlertLevel.INFO,
                server_id=event.server_id,
                timestamp=event.timestamp,
                fields=(("Steam ID", str(event.steam_id)),),
            )

        logger.warning(
            "no alert renderer for event",
            extra={"server_id": event.server_id, "event_type": event.event_type.value},
        )
        return None
