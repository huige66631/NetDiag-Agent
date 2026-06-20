from __future__ import annotations

from netdiag_agent.models import Diagnosis, NetworkSnapshot, PingResult


def _bad_ping(result: PingResult | None, latency_threshold: float, loss_threshold: float) -> bool:
    if result is None:
        return False
    loss = result.packet_loss_percent or 0
    avg = result.avg_ms or 0
    return (not result.success) or loss >= loss_threshold or avg >= latency_threshold


def summarize_dns_comparison(snapshot: NetworkSnapshot) -> str | None:
    compare_items = {
        name: item
        for name, item in snapshot.dns.items()
        if ":" in name and item.elapsed_ms is not None
    }
    if len(compare_items) < 2:
        return None

    local_items = [(name, item) for name, item in compare_items.items() if ":local:" in name]
    public_items = [(name, item) for name, item in compare_items.items() if ":local:" not in name]
    if not local_items or not public_items:
        return None

    best_local_name, best_local = sorted(local_items, key=lambda item: item[1].elapsed_ms or 999999)[0]
    best_public_name, best_public = sorted(public_items, key=lambda item: item[1].elapsed_ms or 999999)[0]
    if best_local.elapsed_ms is None or best_public.elapsed_ms is None:
        return None

    diff = round(abs(best_local.elapsed_ms - best_public.elapsed_ms), 2)
    if best_local.elapsed_ms < best_public.elapsed_ms:
        return (
            f"DNS 对比显示本机 DNS 更快：{best_local_name} 耗时 {best_local.elapsed_ms} ms，"
            f"比最快公共 DNS {best_public_name} 快 {diff} ms。"
        )
    if best_public.elapsed_ms < best_local.elapsed_ms:
        return (
            f"DNS 对比显示公共 DNS 更快：{best_public_name} 耗时 {best_public.elapsed_ms} ms，"
            f"比本机 DNS {best_local_name} 快 {diff} ms。"
        )
    return (
        f"DNS 对比显示本机 DNS 与公共 DNS 速度接近：{best_local_name} 和 {best_public_name} "
        f"耗时差约 {diff} ms。"
    )


def _target_ping_failed_but_dns_ok(snapshot: NetworkSnapshot) -> tuple[str, PingResult] | None:
    dns_targets = {name.split(":")[0] for name, item in snapshot.dns.items() if item.success}
    for name, ping_result in snapshot.pings.items():
        if name in {"gateway", "public_dns"}:
            continue
        if not ping_result.success and name in dns_targets:
            return name, ping_result
    return None


def diagnose(snapshot: NetworkSnapshot) -> Diagnosis:
    evidence: list[str] = []
    causes: list[str] = []
    suggestions: list[str] = []

    gateway = snapshot.pings.get("gateway")
    public_dns = snapshot.pings.get("public_dns")
    external = [value for key, value in snapshot.pings.items() if key not in {"gateway", "public_dns"}]

    if gateway:
        evidence.append(
            f"你电脑到路由器/网关 {gateway.target}: 平均 {gateway.avg_ms} ms, 丢包 {gateway.packet_loss_percent}%"
        )
    if public_dns:
        evidence.append(
            f"你电脑到公共网络目标 {public_dns.target}: 平均 {public_dns.avg_ms} ms, 丢包 {public_dns.packet_loss_percent}%"
        )
    for name, item in snapshot.dns.items():
        status = "成功" if item.success else "失败"
        evidence.append(f"DNS 解析 {name}: {status}, 耗时 {item.elapsed_ms} ms")

    dns_compare_summary = summarize_dns_comparison(snapshot)
    if dns_compare_summary:
        evidence.append(dns_compare_summary)

    gateway_bad = _bad_ping(gateway, latency_threshold=30, loss_threshold=5)
    public_bad = _bad_ping(public_dns, latency_threshold=120, loss_threshold=5)
    external_bad_count = sum(1 for item in external if _bad_ping(item, 150, 5))
    dns_slow = any((item.elapsed_ms or 0) > 800 or not item.success for item in snapshot.dns.values())
    failed_ping_with_ok_dns = _target_ping_failed_but_dns_ok(snapshot)

    if gateway_bad:
        causes.append("更像是你这边到路由器/无线接入这段链路不稳定，不像是单个网站的问题。")
        suggestions.extend(
            [
                "先靠近路由器或换到信号更强的位置，再复测一次。",
                "如果方便，优先试一次有线网络，看看问题会不会消失。",
                "先关闭代理、加速器、热点共享之类会改路由的程序，再试一次。",
            ]
        )
    elif dns_slow and not public_bad:
        causes.append("更像是 DNS 解析偏慢，所以网址打开前会先卡一下，但整条网络不一定有问题。")
        suggestions.extend(
            [
                "你现在就可以先把 DNS 临时换成 223.5.5.5 或 119.29.29.29，再复测。",
                "如果换 DNS 后明显变快，后面就优先保留这个设置继续观察。",
            ]
        )
        if dns_compare_summary and "公共 DNS 更快" in dns_compare_summary:
            suggestions.append("这次结果里公共 DNS 更快，优先试公共 DNS 会更有意义。")
    elif failed_ping_with_ok_dns and not public_bad:
        target_name, ping_result = failed_ping_with_ok_dns
        causes.append("这个目标域名能正常解析，但 Ping 不通，更像是目标站点禁 Ping、CDN 策略限制，或者这条路径对 ICMP 不友好。")
        evidence.append(f"{target_name} 的 DNS 解析成功，但 {ping_result.target} 的 Ping 没有成功返回。")
        suggestions.extend(
            [
                "先直接用浏览器打开这个站点，再判断它是不是真的不能用。",
                "如果网页能打开但 Ping 不通，先别把问题归到你自己网络上。",
                "如果只有这一个网站有问题，优先换同类网站做对照测试。",
            ]
        )
    elif public_bad and external_bad_count >= 1:
        causes.append("更像是当前网络出口或上游链路拥塞，不太像你电脑本身的问题。")
        suggestions.extend(
            [
                "换个时间段再测一次，看看晚高峰和非高峰差别大不大。",
                "可以用手机热点做一次对照测试，判断是不是当前这条网络的问题。",
                "如果热点正常而当前网络明显差，后面就优先避免在这条网络上做高实时需求的事。",
            ]
        )
    elif external_bad_count == 1:
        causes.append("更像是某个网站、服务端、CDN 或访问路径的问题，不像你整台电脑的网络都坏了。")
        suggestions.extend(
            [
                "先换同类网站试一下，看看是不是只有这一个目标异常。",
                "如果只是单个网站慢，优先怀疑目标站点或访问路径，而不是本地整网。",
            ]
        )
        if dns_compare_summary and "公共 DNS 更快" in dns_compare_summary:
            suggestions.append("如果这是域名访问问题，可以先切换到更快的公共 DNS 再复测。")
    else:
        causes.append("这次检测里，你本机到网关、公网和 DNS 都比较正常，没有看到明显网络异常。")
        suggestions.extend(
            [
                "如果你体感还是卡，建议在问题真的出现的时候再测一次。",
                "如果是偶发卡顿，优先开 5-10 分钟短时监控去抓抖动和丢包。",
            ]
        )

    severity = (
        "high"
        if gateway_bad or (public_bad and external_bad_count >= 2)
        else "medium"
        if dns_slow or public_bad or failed_ping_with_ok_dns
        else "low"
    )
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
