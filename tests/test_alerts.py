"""Alert rendering and engine dispatch."""

from datetime import datetime, timezone

import pytest

from rustbot.domain.alerts import Alert, AlertEngine, AlertLevel
from rustbot.events import (
    ServerStatusChanged,
    TeamMemberStatusChanged,
    WipeDetected,
)

NOW = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
SID = "1.2.3.4:28082"


class RecordingSink:
    def __init__(self):
        self.alerts = []

    async def send_alert(self, alert):
        self.alerts.append(alert)


def test_render_server_offline_is_warning():
    alert = AlertEngine.render(
        ServerStatusChanged(server_id=SID, timestamp=NOW, online=False)
    )
    assert isinstance(alert, Alert)
    assert alert.level is AlertLevel.WARNING


def test_render_server_online_is_good():
    alert = AlertEngine.render(
        ServerStatusChanged(server_id=SID, timestamp=NOW, online=True)
    )
    assert alert.level is AlertLevel.GOOD


def test_render_wipe_has_field():
    alert = AlertEngine.render(
        WipeDetected(server_id=SID, timestamp=NOW, wipe_time=1_700_000_000)
    )
    assert alert.level is AlertLevel.WARNING
    assert alert.fields and alert.fields[0][0] == "Wipe time"


def test_render_team_member_offline():
    alert = AlertEngine.render(
        TeamMemberStatusChanged(
            server_id=SID, timestamp=NOW, steam_id=42, name="Alice", online=False
        )
    )
    assert "Alice" in alert.description
    assert alert.level is AlertLevel.INFO


@pytest.mark.asyncio
async def test_engine_dispatches_to_sink():
    sink = RecordingSink()
    engine = AlertEngine(sink=sink)
    await engine.handle_event(
        ServerStatusChanged(server_id=SID, timestamp=NOW, online=False)
    )
    assert len(sink.alerts) == 1
    assert sink.alerts[0].title.endswith("Server Offline")
