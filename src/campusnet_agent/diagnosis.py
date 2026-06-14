from __future__ import annotations

from campusnet_agent.models import Diagnosis, NetworkSnapshot, PingResult


def _bad_ping(result: PingResult | None, latency_threshold: float, loss_threshold: float) -> bool:
    if result is None:
        return False
    loss = result.packet_loss_percent or 0
    avg = result.avg_ms or 0
    return (not result.success) or loss >= loss_threshold or avg >= latency_threshold


def diagnose(snapshot: NetworkSnapshot) -> Diagnosis:
    evidence: list[str] = []
    causes: list[str] = []
    suggestions: list[str] = []

    gateway = snapshot.pings.get("gateway")
    public_dns = snapshot.pings.get("public_dns")
    external = [value for key, value in snapshot.pings.items() if key not in {"gateway", "public_dns"}]

    if gateway:
        evidence.append(
            f"网关 {gateway.target}: 平均 {gateway.avg_ms} ms, 丢包 {gateway.packet_loss_percent}%"
        )
    if public_dns:
        evidence.append(
            f"公共 DNS {public_dns.target}: 平均 {public_dns.avg_ms} ms, 丢包 {public_dns.packet_loss_percent}%"
        )
    for name, item in snapshot.dns.items():
        status = "成功" if item.success else "失败"
        evidence.append(f"DNS 解析 {name}: {status}, 耗时 {item.elapsed_ms} ms")

    gateway_bad = _bad_ping(gateway, latency_threshold=30, loss_threshold=5)
    public_bad = _bad_ping(public_dns, latency_threshold=120, loss_threshold=5)
    external_bad_count = sum(1 for item in external if _bad_ping(item, 150, 5))
    dns_slow = any((item.elapsed_ms or 0) > 800 or not item.success for item in snapshot.dns.values())

    if gateway_bad:
        causes.append("本机到校园网接入点链路异常，可能是 Wi-Fi 信号弱、宿舍 AP 拥塞或本机网卡问题。")
        suggestions.extend(
            [
                "靠近路由器/AP 或切换到信号更强的校园网热点后复测。",
                "如果可用，优先用有线网络对比测试，排除无线链路问题。",
                "关闭代理、加速器、热点共享等可能影响路由的程序后复测。",
            ]
        )
    elif dns_slow and not public_bad:
        causes.append("DNS 解析异常，表现为 IP 连通性还可以，但域名访问慢或失败。")
        suggestions.extend(
            [
                "临时切换 DNS 到 223.5.5.5、119.29.29.29 或学校推荐 DNS 后复测。",
                "记录当前 DNS 服务器和解析耗时，作为反馈给网络中心的证据。",
            ]
        )
    elif public_bad and external_bad_count >= 1:
        causes.append("校园网出口或上游链路可能拥塞，尤其适合晚高峰访问外网慢的场景。")
        suggestions.extend(
            [
                "在非高峰时段和晚高峰各运行一次诊断，对比延迟和丢包变化。",
                "用手机热点做对照测试，如果热点正常，问题更可能在校园网出口侧。",
                "把报告中的网关正常、公网异常证据反馈给学校网络中心。",
            ]
        )
    elif external_bad_count == 1:
        causes.append("问题可能集中在某个目标网站或其 CDN/路由路径，而不是整个校园网。")
        suggestions.extend(
            [
                "更换同类网站测试，例如视频站、搜索站、游戏平台分别测一次。",
                "保留 traceroute 结果，观察是否某一跳开始明显升高。",
            ]
        )
    else:
        causes.append("当前基础连通性正常，没有发现明显校园网侧异常。")
        suggestions.extend(
            [
                "如果体感仍然卡，建议开启 5-10 分钟周期监控，观察抖动和间歇性丢包。",
                "针对游戏卡顿，应重点关注丢包和抖动，而不是只看下载速度。",
            ]
        )

    severity = "high" if gateway_bad or (public_bad and external_bad_count >= 2) else "medium" if dns_slow or public_bad else "low"
    summary = causes[0]

    diagnosis = Diagnosis(
        summary=summary,
        severity=severity,
        likely_causes=causes,
        evidence=evidence,
        suggestions=suggestions,
    )
    snapshot.diagnosis = diagnosis
    return diagnosis

