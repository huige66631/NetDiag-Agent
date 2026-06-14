from __future__ import annotations

import ipaddress
import platform
import re
import socket
import subprocess
import time
from datetime import datetime

from netdiag_agent.models import DnsResult, NetworkSnapshot, PingResult, TraceHop, TraceResult


DEFAULT_TARGETS = {
    "public_dns": "223.5.5.5",
    "baidu": "www.baidu.com",
    "bilibili": "www.bilibili.com",
}


def _run_command(command: list[str], timeout: int = 20) -> tuple[bool, str, str]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="gbk" if platform.system().lower() == "windows" else "utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return False, exc.stdout or "", f"Command timed out after {timeout}s"
    except OSError as exc:
        return False, "", str(exc)
    return completed.returncode == 0, completed.stdout, completed.stderr


def get_default_gateway() -> str | None:
    if platform.system().lower() == "windows":
        ok, out, _ = _run_command(["ipconfig"], timeout=10)
        if not ok and not out:
            return None
        lines = out.splitlines()
        for index, line in enumerate(lines):
            if "默认网关" not in line and "Default Gateway" not in line:
                continue
            candidates = [line]
            next_index = index + 1
            while next_index < len(lines) and lines[next_index].startswith(" " * 30):
                candidates.append(lines[next_index])
                next_index += 1
            for candidate in candidates:
                match = re.search(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b", candidate)
                if match:
                    return match.group(0)
        return None

    ok, out, _ = _run_command(["sh", "-c", "ip route | awk '/default/ {print $3; exit}'"], timeout=10)
    return out.strip() if ok and out.strip() else None


def get_dns_servers() -> list[str]:
    servers: list[str] = []
    if platform.system().lower() == "windows":
        ok, out, _ = _run_command(["ipconfig", "/all"], timeout=15)
        if not ok and not out:
            return []
        lines = out.splitlines()
        for index, line in enumerate(lines):
            if "DNS Servers" not in line and "DNS 服务器" not in line:
                continue
            candidates = [line]
            next_index = index + 1
            while next_index < len(lines) and lines[next_index].startswith(" " * 30):
                candidates.append(lines[next_index])
                next_index += 1
            for candidate in candidates:
                for ip in re.findall(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b", candidate):
                    try:
                        ipaddress.ip_address(ip)
                    except ValueError:
                        continue
                    if ip not in servers:
                        servers.append(ip)
        return servers[:6]

    ok, out, _ = _run_command(["sh", "-c", "grep '^nameserver' /etc/resolv.conf"], timeout=10)
    if ok:
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] not in servers:
                servers.append(parts[1])
    return servers


def ping(target: str, count: int = 4, timeout: int = 10) -> PingResult:
    system = platform.system().lower()
    command = ["ping", "-n", str(count), target] if system == "windows" else ["ping", "-c", str(count), target]
    ok, out, err = _run_command(command, timeout=timeout)
    text = out + "\n" + err

    sent = received = None
    loss = min_ms = avg_ms = max_ms = None

    if system == "windows":
        packets = re.search(r"已发送 = (\d+).*?已接收 = (\d+).*?丢失 = (\d+)", text, re.S)
        if not packets:
            packets = re.search(r"Sent = (\d+).*?Received = (\d+).*?Lost = (\d+)", text, re.S)
        if packets:
            sent = int(packets.group(1))
            received = int(packets.group(2))
            lost = int(packets.group(3))
            loss = round((lost / sent) * 100, 2) if sent else None

        stats = re.search(r"最短 = (\d+)ms.*?最长 = (\d+)ms.*?平均 = (\d+)ms", text, re.S)
        if not stats:
            stats = re.search(r"Minimum = (\d+)ms.*?Maximum = (\d+)ms.*?Average = (\d+)ms", text, re.S)
        if stats:
            min_ms = float(stats.group(1))
            max_ms = float(stats.group(2))
            avg_ms = float(stats.group(3))
    else:
        packets = re.search(r"(\d+) packets transmitted, (\d+) received.*?(\d+(?:\.\d+)?)% packet loss", text)
        if packets:
            sent = int(packets.group(1))
            received = int(packets.group(2))
            loss = float(packets.group(3))
        stats = re.search(r"min/avg/max/(?:mdev|stddev) = ([\d.]+)/([\d.]+)/([\d.]+)", text)
        if stats:
            min_ms = float(stats.group(1))
            avg_ms = float(stats.group(2))
            max_ms = float(stats.group(3))

    success = ok or (received is not None and received > 0)
    return PingResult(
        target=target,
        success=success,
        packets_sent=sent,
        packets_received=received,
        packet_loss_percent=loss,
        min_ms=min_ms,
        avg_ms=avg_ms,
        max_ms=max_ms,
        raw=text.strip(),
        error=None if success else err.strip() or "ping failed",
    )


def dns_lookup(host: str, dns_server: str | None = None) -> DnsResult:
    start = time.perf_counter()
    addresses: list[str] = []
    raw = ""
    error = None

    try:
        if dns_server and platform.system().lower() == "windows":
            ok, out, err = _run_command(["nslookup", host, dns_server], timeout=10)
            raw = out + "\n" + err
            for ip in re.findall(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b", raw):
                if ip != dns_server and ip not in addresses:
                    addresses.append(ip)
            success = ok and bool(addresses)
        else:
            addresses = sorted({info[4][0] for info in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)})
            success = bool(addresses)
    except (OSError, socket.gaierror) as exc:
        success = False
        error = str(exc)

    elapsed = round((time.perf_counter() - start) * 1000, 2)
    return DnsResult(
        host=host,
        success=success,
        addresses=addresses,
        elapsed_ms=elapsed,
        dns_server=dns_server,
        raw=raw.strip(),
        error=error if not success else None,
    )


def traceroute(target: str, max_hops: int = 15, timeout: int = 30) -> TraceResult:
    system = platform.system().lower()
    command = ["tracert", "-h", str(max_hops), target] if system == "windows" else ["traceroute", "-m", str(max_hops), target]
    ok, out, err = _run_command(command, timeout=timeout)
    text = out + "\n" + err
    hops: list[TraceHop] = []

    for line in text.splitlines():
        stripped = line.strip()
        match = re.match(r"^(\d+)\s+(.+)$", stripped)
        if not match:
            continue
        hop_no = int(match.group(1))
        latencies = [float(x) for x in re.findall(r"(\d+)\s*ms", stripped)]
        latency = round(sum(latencies) / len(latencies), 2) if latencies else None
        ip_match = re.search(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b", stripped)
        hops.append(TraceHop(hop=hop_no, address=ip_match.group(0) if ip_match else None, latency_ms=latency, raw=stripped))

    return TraceResult(target=target, success=ok or bool(hops), hops=hops, raw=text.strip(), error=None if ok or hops else err.strip())


def collect_snapshot(targets: dict[str, str] | None = None, include_trace: bool = True) -> NetworkSnapshot:
    selected_targets = targets or DEFAULT_TARGETS
    gateway = get_default_gateway()
    dns_servers = get_dns_servers()

    pings: dict[str, PingResult] = {}
    if gateway:
        pings["gateway"] = ping(gateway)
    for name, target in selected_targets.items():
        pings[name] = ping(target)

    dns_results = {
        name: dns_lookup(target, dns_servers[0] if dns_servers else None)
        for name, target in selected_targets.items()
        if not re.fullmatch(r"(?:[0-9]{1,3}\.){3}[0-9]{1,3}", target)
    }

    traces: dict[str, TraceResult] = {}
    if include_trace:
        for name, target in selected_targets.items():
            traces[name] = traceroute(target)

    return NetworkSnapshot(
        created_at=datetime.now(),
        gateway=gateway,
        dns_servers=dns_servers,
        pings=pings,
        dns=dns_results,
        traces=traces,
    )

