from netdiag_agent.models import DnsResult
from netdiag_agent.probe import compare_dns


def test_compare_dns_includes_local_and_public(monkeypatch):
    def fake_dns_lookup(host, dns_server=None):
        return DnsResult(
            host=host,
            success=True,
            addresses=["1.1.1.1"],
            elapsed_ms=20,
            dns_server=dns_server,
        )

    monkeypatch.setattr("netdiag_agent.probe.dns_lookup", fake_dns_lookup)

    results = compare_dns("www.baidu.com", dns_servers=["192.168.1.1"])

    assert "local:192.168.1.1" in results
    assert "aliyun_public" in results
    assert "tencent_public" in results
