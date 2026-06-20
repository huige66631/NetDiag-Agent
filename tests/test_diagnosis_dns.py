from datetime import datetime

from netdiag_agent.diagnosis import diagnose, summarize_dns_comparison
from netdiag_agent.models import DnsResult, NetworkSnapshot, PingResult


def test_summarize_dns_comparison_prefers_public_dns():
    snapshot = NetworkSnapshot(
        created_at=datetime.now(),
        gateway="192.168.1.1",
        dns_servers=["192.168.1.1"],
        pings={},
        dns={
            "example.com:local:192.168.1.1": DnsResult(
                host="example.com",
                success=True,
                elapsed_ms=90,
                dns_server="192.168.1.1",
            ),
            "example.com:aliyun_public": DnsResult(
                host="example.com",
                success=True,
                elapsed_ms=30,
                dns_server="223.5.5.5",
            ),
        },
        traces={},
    )

    summary = summarize_dns_comparison(snapshot)

    assert summary is not None
    assert "公共 DNS 更快" in summary


def test_diagnose_adds_dns_comparison_evidence():
    snapshot = NetworkSnapshot(
        created_at=datetime.now(),
        gateway="192.168.1.1",
        dns_servers=["192.168.1.1"],
        pings={},
        dns={
            "example.com:local:192.168.1.1": DnsResult(
                host="example.com",
                success=True,
                elapsed_ms=90,
                dns_server="192.168.1.1",
            ),
            "example.com:aliyun_public": DnsResult(
                host="example.com",
                success=True,
                elapsed_ms=30,
                dns_server="223.5.5.5",
            ),
        },
        traces={},
    )

    result = diagnose(snapshot)

    assert any("DNS 对比显示公共 DNS 更快" in item for item in result.evidence)


def test_failed_ping_with_normal_dns_uses_target_side_explanation():
    snapshot = NetworkSnapshot(
        created_at=datetime.now(),
        gateway="192.168.1.1",
        dns_servers=["192.168.1.1"],
        pings={
            "gateway": PingResult(target="192.168.1.1", success=True, avg_ms=2, packet_loss_percent=0),
            "public_dns": PingResult(target="223.5.5.5", success=True, avg_ms=20, packet_loss_percent=0),
            "example.com": PingResult(target="example.com", success=False, error="timeout"),
        },
        dns={
            "example.com:local:192.168.1.1": DnsResult(
                host="example.com",
                success=True,
                elapsed_ms=40,
                dns_server="192.168.1.1",
            ),
            "example.com:aliyun_public": DnsResult(
                host="example.com",
                success=True,
                elapsed_ms=60,
                dns_server="223.5.5.5",
            ),
        },
        traces={},
    )

    result = diagnose(snapshot)

    assert "目标域名能正常解析，但 Ping 不通" in result.summary
    assert any("example.com 的 DNS 解析成功" in item and "Ping" in item for item in result.evidence)
