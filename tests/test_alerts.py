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
    """Verify offline alerts are rendered with WARNING level.
    
    Confirms that server offline status is treated as a warning-level event.
    """
    alert = AlertEngine.render(
        ServerStatusChanged(server_id=SID, timestamp=NOW, online=False)
    )
    assert isinstance(alert, Alert)
    assert alert.level is AlertLevel.WARNING


def test_render_server_online_is_good():
    """Verify online alerts are rendered with GOOD level.
    
    Confirms that server recovery is treated as good news.
    """
    alert = AlertEngine.render(
        ServerStatusChanged(server_id=SID, timestamp=NOW, online=True)
    )
    assert alert.level is AlertLevel.GOOD


def test_render_wipe_has_field():
    """Verify wipe alerts include the wipe timestamp in embed fields.
    
    Ensures players see when the new wipe will be/was.
    """
    alert = AlertEngine.render(
        WipeDetected(server_id=SID, timestamp=NOW, wipe_time=1_700_000_000)
    )
    assert alert.level is AlertLevel.WARNING
    assert alert.fields and alert.fields[0][0] == "Wipe time"


def test_render_team_member_offline():
    """Verify teammate offline alerts include the member's name.
    
    Confirms player names are included in team status change notifications.
    """
    alert = AlertEngine.render(
        TeamMemberStatusChanged(
            server_id=SID, timestamp=NOW, steam_id=42, name="Alice", online=False
        )
    )
    assert "Alice" in alert.description
    assert alert.level is AlertLevel.INFO


@pytest.mark.asyncio
async def test_engine_dispatches_to_sink():
    """Verify AlertEngine forwards rendered alerts to the sink (Discord layer).
    
    Ensures the alert pipeline integrates: event -> engine -> sink.
    """
    sink = RecordingSink()
    engine = AlertEngine(sink=sink)
    await engine.handle_event(
        ServerStatusChanged(server_id=SID, timestamp=NOW, online=False)
    )
    assert len(sink.alerts) == 1
    assert sink.alerts[0].title.endswith("Server Offline")
