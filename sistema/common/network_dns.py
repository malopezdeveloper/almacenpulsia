#!/usr/bin/env python3
"""Utilidades de red/DNS para los instaladores de PULSIA Inventario.

No cambia la red local. Solo descubre DNS y, opcionalmente, realiza una
actualizacion RFC2136 cuando se dispone de una clave TSIG autorizada.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import ipaddress
import json
import os
import re
import socket
import sys
import platform
import subprocess
from pathlib import Path


def tcp53(ip: str, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((ip, 53), timeout=timeout):
            return True
    except OSError:
        return False


def scan_dns(cidr: str, limit: int = 512) -> list[str]:
    net = ipaddress.ip_network(cidr, strict=False)
    hosts = [str(x) for x in net.hosts()]
    if len(hosts) > limit:
        # No se barre una red grande completa; se prueban direcciones habituales.
        base = int(net.network_address)
        candidates = []
        for last in (1, 2, 10, 11, 20, 53, 100, 200, 254):
            addr = ipaddress.ip_address(base + last)
            if addr in net:
                candidates.append(str(addr))
        hosts = candidates
    found: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=48) as ex:
        futs = {ex.submit(tcp53, ip): ip for ip in hosts}
        for fut in concurrent.futures.as_completed(futs):
            if fut.result():
                found.append(futs[fut])
    return sorted(found, key=lambda x: ipaddress.ip_address(x))


def parse_bind_key(path: str) -> tuple[str, str, str]:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    name_m = re.search(r'key\s+["\']?([^"\'\s{]+)["\']?\s*\{', text, re.I)
    alg_m = re.search(r'algorithm\s+([^;\s]+)\s*;', text, re.I)
    secret_m = re.search(r'secret\s+["\']([^"\']+)["\']\s*;', text, re.I)
    if not (name_m and secret_m):
        raise ValueError("No se pudo interpretar el fichero TSIG BIND")
    alg = (alg_m.group(1) if alg_m else "hmac-sha256").rstrip(".").lower()
    return name_m.group(1).rstrip("."), alg, secret_m.group(1)


def update_dns(server: str, zone: str, host: str, address: str, ttl: int,
               key_file: str | None, key_name: str | None,
               key_secret: str | None, algorithm: str) -> dict:
    try:
        import dns.query
        import dns.rcode
        import dns.tsigkeyring
        import dns.update
    except Exception as exc:
        raise RuntimeError("dnspython no esta instalado en el entorno virtual") from exc

    zone = zone.rstrip(".")
    fqdn = host.rstrip(".")
    if not fqdn.lower().endswith("." + zone.lower()) and fqdn.lower() != zone.lower():
        fqdn = f"{fqdn}.{zone}"
    rel = fqdn[: -(len(zone) + 1)] if fqdn.lower().endswith("." + zone.lower()) else "@"

    keyring = None
    keyalgorithm = None
    if key_file:
        key_name, algorithm, key_secret = parse_bind_key(key_file)
    if key_name and key_secret:
        keyring = dns.tsigkeyring.from_text({key_name.rstrip("."): key_secret})
        keyalgorithm = algorithm

    update = dns.update.Update(zone, keyring=keyring, keyalgorithm=keyalgorithm)
    update.replace(rel, ttl, "A", address)
    response = dns.query.tcp(update, server, timeout=6)
    rc = response.rcode()
    if rc != dns.rcode.NOERROR:
        raise RuntimeError(f"El DNS rechazo la actualizacion: {dns.rcode.to_text(rc)}")
    return {"server": server, "zone": zone, "fqdn": fqdn, "address": address, "ttl": ttl}



def _run_json_powershell(script: str) -> dict:
    proc = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True, timeout=12)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "PowerShell no pudo consultar la red")
    return json.loads(proc.stdout.strip())


def current_network() -> dict:
    """Devuelve la interfaz IPv4 usada por la ruta por defecto sin cambiar nada."""
    if os.name == "nt":
        ps = "$r=Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction Stop | Sort-Object RouteMetric,InterfaceMetric | Select-Object -First 1; $i=Get-NetIPAddress -InterfaceIndex $r.InterfaceIndex -AddressFamily IPv4 -AddressState Preferred -ErrorAction Stop | Where-Object {$_.IPAddress -notlike '169.254.*'} | Select-Object -First 1; $a=Get-NetAdapter -InterfaceIndex $r.InterfaceIndex -ErrorAction Stop; $d=(Get-DnsClientServerAddress -InterfaceIndex $r.InterfaceIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue).ServerAddresses; $s=(Get-DnsClient -InterfaceIndex $r.InterfaceIndex -ErrorAction SilentlyContinue).ConnectionSpecificSuffix; [pscustomobject]@{interface=$a.Name;interface_index=$r.InterfaceIndex;ip=$i.IPAddress;prefix=[int]$i.PrefixLength;gateway=$r.NextHop;mac=($a.MacAddress -replace '-',':').ToLower();dns=@($d);zone=$s;hostname=$env:COMPUTERNAME;platform='windows'} | ConvertTo-Json -Compress"
        return _run_json_powershell(ps)
    route = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True, timeout=8)
    line = next((x for x in route.stdout.splitlines() if x.startswith("default ")), "")
    if not line:
        raise RuntimeError("No se encontró una ruta IPv4 por defecto")
    parts = line.split()
    iface = parts[parts.index("dev") + 1] if "dev" in parts else ""
    gateway = parts[parts.index("via") + 1] if "via" in parts else ""
    if not iface:
        raise RuntimeError("No se pudo determinar la interfaz de la ruta por defecto")
    addr = subprocess.run(["ip", "-o", "-4", "addr", "show", "dev", iface, "scope", "global"], capture_output=True, text=True, timeout=8)
    cidr = ""
    for row in addr.stdout.splitlines():
        bits = row.split()
        if "inet" in bits:
            candidate = bits[bits.index("inet") + 1]
            if not candidate.startswith("169.254."):
                cidr = candidate
                break
    if not cidr:
        raise RuntimeError("No se encontró una IPv4 LAN utilizable")
    ipif = ipaddress.ip_interface(cidr)
    mac_path = Path("/sys/class/net") / iface / "address"
    mac = mac_path.read_text().strip().lower() if mac_path.exists() else ""
    dns, zone = [], ""
    try:
        text = Path("/etc/resolv.conf").read_text(errors="replace")
        for row in text.splitlines():
            fields = row.split()
            if len(fields) >= 2 and fields[0] == "nameserver" and not fields[1].startswith("127."):
                dns.append(fields[1])
            elif len(fields) >= 2 and fields[0] in {"search", "domain"} and not zone:
                zone = fields[1]
    except OSError:
        pass
    return {"interface": iface, "interface_index": None, "ip": str(ipif.ip), "prefix": ipif.network.prefixlen, "gateway": gateway, "mac": mac, "dns": dns, "zone": zone, "hostname": socket.gethostname(), "platform": platform.system().lower()}

def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("current")
    s = sub.add_parser("scan")
    s.add_argument("--cidr", required=True)
    u = sub.add_parser("update")
    u.add_argument("--server", required=True)
    u.add_argument("--zone", required=True)
    u.add_argument("--host", default="almacen")
    u.add_argument("--address", required=True)
    u.add_argument("--ttl", type=int, default=300)
    u.add_argument("--key-file")
    u.add_argument("--key-name")
    u.add_argument("--key-secret")
    u.add_argument("--algorithm", default="hmac-sha256")
    args = p.parse_args()

    try:
        if args.cmd == "current":
            print(json.dumps(current_network(), ensure_ascii=False))
        elif args.cmd == "scan":
            print(json.dumps({"dns_servers": scan_dns(args.cidr)}, ensure_ascii=False))
        else:
            result = update_dns(args.server, args.zone, args.host, args.address, args.ttl,
                                args.key_file, args.key_name, args.key_secret, args.algorithm)
            print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
