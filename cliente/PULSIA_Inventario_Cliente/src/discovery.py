from __future__ import annotations

import concurrent.futures
import ipaddress
import platform
import re
import socket
import ssl
import subprocess
from dataclasses import dataclass
from typing import List, Optional

import psutil

from app_config import SERVICE_HOSTNAME, SERVICE_PORT, ServerInfo


@dataclass
class ProbeResult:
    server: Optional[ServerInfo]
    error: str = ""


def is_allowed_server_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr.version != 4 or addr.is_loopback or addr.is_multicast or addr.is_unspecified:
        return False
    return bool(addr.is_private or addr.is_link_local)


def _run(cmd: list[str], timeout: float = 3.0) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return (p.stdout or "") + "\n" + (p.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return ""


def get_mac_for_ip(ip: str) -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            sock.connect_ex((ip, SERVICE_PORT))
    except OSError:
        pass

    if platform.system() == "Windows":
        text = _run(["arp", "-a", ip])
        match = re.search(rf"\b{re.escape(ip)}\s+([0-9a-fA-F-]{{17}})", text)
    else:
        text = _run(["ip", "neigh", "show", ip])
        match = re.search(r"\blladdr\s+([0-9a-fA-F:]{17})", text)
        if not match:
            text = _run(["arp", "-n", ip])
            match = re.search(r"([0-9a-fA-F:]{17})", text)
    return match.group(1).upper() if match else ""


def reverse_hostname(ip: str) -> str:
    try:
        return socket.gethostbyaddr(ip)[0]
    except OSError:
        return ""


def probe_server(ip: str, timeout: float = 2.0) -> ProbeResult:
    if not is_allowed_server_ip(ip):
        return ProbeResult(None, "La IP no pertenece a una red local permitida.")

    raw = None
    tls = None
    try:
        raw = socket.create_connection((ip, SERVICE_PORT), timeout=timeout)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        tls = ctx.wrap_socket(raw, server_hostname=SERVICE_HOSTNAME)
        tls.settimeout(timeout)

        req = (
            f"GET / HTTP/1.1\r\n"
            f"Host: {SERVICE_HOSTNAME}\r\n"
            "User-Agent: PulsiaInventarioCliente/2.0\r\n"
            "Accept: */*\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")
        tls.sendall(req)

        chunks = []
        total = 0
        while total < 16384:
            data = tls.recv(min(4096, 16384 - total))
            if not data:
                break
            chunks.append(data)
            total += len(data)
            if b"\r\n\r\n" in b"".join(chunks):
                break

        text = b"".join(chunks).decode("iso-8859-1", errors="replace").lower()
        login_marker = "location: /cuenta/login/?next=/" in text
        stack_marker = "server: waitress" in text or "via: 1.1 caddy" in text or "server: caddy" in text
        if not (login_marker and stack_marker):
            return ProbeResult(None, "El HTTPS responde, pero no coincide con PULSIA Inventario.")

        info = ServerInfo(
            ip=ip,
            mac=get_mac_for_ip(ip),
            reverse_hostname=reverse_hostname(ip),
        )
        info.touch()
        return ProbeResult(info)
    except (socket.timeout, TimeoutError):
        return ProbeResult(None, "Tiempo de espera agotado.")
    except ConnectionRefusedError:
        return ProbeResult(None, "TCP/443 rechazado.")
    except ssl.SSLError as exc:
        return ProbeResult(None, f"Error TLS: {exc}")
    except OSError as exc:
        return ProbeResult(None, str(exc))
    finally:
        try:
            if tls is not None:
                tls.close()
            elif raw is not None:
                raw.close()
        except OSError:
            pass


def _local_networks() -> List[ipaddress.IPv4Network]:
    nets: List[ipaddress.IPv4Network] = []
    for _, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if addr.family != socket.AF_INET or not addr.address or addr.address.startswith("127."):
                continue
            try:
                net = ipaddress.ip_network(f"{addr.address}/{addr.netmask}", strict=False)
            except (ValueError, TypeError):
                continue
            if not (net.is_private or net.is_link_local):
                continue
            # Limit discovery to /24 to avoid aggressive scans on VPN/corporate ranges.
            if net.num_addresses > 256:
                net = ipaddress.ip_network(f"{addr.address}/24", strict=False)
            if net not in nets:
                nets.append(net)
    return nets


def candidate_ips() -> List[str]:
    result: List[str] = []
    seen = set()
    for net in _local_networks():
        for host in net.hosts():
            ip = str(host)
            if ip not in seen:
                seen.add(ip)
                result.append(ip)
    return result


def discover_servers(preferred: Optional[ServerInfo] = None, max_workers: int = 48, progress_cb=None) -> List[ServerInfo]:
    ordered: List[str] = []
    if preferred and is_allowed_server_ip(preferred.ip):
        ordered.append(preferred.ip)

    try:
        resolved = socket.gethostbyname(SERVICE_HOSTNAME)
        if is_allowed_server_ip(resolved) and resolved not in ordered:
            ordered.append(resolved)
    except OSError:
        pass

    for ip in candidate_ips():
        if ip not in ordered:
            ordered.append(ip)

    total = len(ordered)
    checked = 0

    for ip in ordered[:2]:
        result = probe_server(ip, 1.5)
        checked += 1
        if progress_cb:
            progress_cb(checked, total, ip)
        if result.server:
            return [result.server]

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
    futures = {executor.submit(probe_server, ip, 1.2): ip for ip in ordered[2:]}
    try:
        for future in concurrent.futures.as_completed(futures):
            ip = futures[future]
            checked += 1
            if progress_cb:
                progress_cb(checked, total, ip)
            try:
                result = future.result()
            except Exception:
                continue
            if result.server:
                for pending in futures:
                    pending.cancel()
                executor.shutdown(wait=False, cancel_futures=True)
                return [result.server]
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return []
