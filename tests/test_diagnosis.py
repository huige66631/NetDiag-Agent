from datetime import datetime

from netdiag_agent.diagnosis import diagnose
from netdiag_agent.models import NetworkSnapshot, PingResult


def test_gateway_problem_has_wifi_suggestion():
    snapshot = NetworkSnapshot(
        created_at=datetime.now(),
        gateway="192.168.1.1",
        dns_servers=["223.5.5.5"],
        pings={
            "gateway": PingResult(
                target="192.168.1.1",
                success=True,
                avg_ms=80,
                packet_loss_percent=8,
            )
        },
        dns={},
        traces={},
    )

    result = diagnose(snapshot)

    assert result.severity == "high"
    assert "网关" in result.summary

