from __future__ import annotations

import ctypes
import ipaddress
import os
import platform
import socket
import ssl
import hashlib
import subprocess
import sys
import time

import psutil
from pathlib import Path
from shutil import which

from app_config import SERVICE_HOSTNAME, bundled_ca_path
from discovery import is_allowed_server_ip


def hosts_path() -> Path:
    if platform.system() == "Windows":
        return Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "drivers" / "etc" / "hosts"
    return Path("/etc/hosts")


def current_host_ip(hostname: str = SERVICE_HOSTNAME) -> str:
    try:
        content = hosts_path().read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for raw in content.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2 and hostname.lower() in [x.lower() for x in parts[1:]]:
            return parts[0]
    return ""


def resolved_host_ips(hostname: str = SERVICE_HOSTNAME) -> list[str]:
    """Return IPv4 addresses currently resolved by the OS resolver."""
    found: list[str] = []
    try:
        for family, _, _, _, sockaddr in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = sockaddr[0]
            if ip not in found:
                found.append(ip)
    except OSError:
        pass
    return found


def dns_is_consistent(expected_ip: str, hostname: str = SERVICE_HOSTNAME) -> bool:
    """
    Consistent means the local hosts override points to the expected server and
    the OS resolver either resolves to that address or has no answer yet.
    """
    host_ip = current_host_ip(hostname)
    resolved = resolved_host_ips(hostname)
    if host_ip != expected_ip:
        return False
    return not resolved or expected_ip in resolved



def local_ipv4_addresses() -> set[str]:
    addresses: set[str] = set()
    try:
        for addrs in psutil.net_if_addrs().values():
            for addr in addrs:
                if addr.family == socket.AF_INET and addr.address:
                    addresses.add(addr.address)
    except Exception:
        pass
    return addresses


def server_is_local_machine(ip: str) -> bool:
    return ip in local_ipv4_addresses()

def is_admin() -> bool:
    if platform.system() == "Windows":
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return os.geteuid() == 0


def _validate_hosts_change(ip: str, hostname: str) -> None:
    if hostname.lower() != SERVICE_HOSTNAME.lower():
        raise ValueError("Solo se permite configurar el hostname de PULSIA Inventario.")
    if not is_allowed_server_ip(ip):
        raise ValueError("La IP debe pertenecer a una red local permitida.")


def _remove_alias_from_hosts_line(raw: str, hostname: str) -> str | None:
    body, sep, comment = raw.partition("#")
    parts = body.split()
    if len(parts) < 2:
        return raw
    ip = parts[0]
    aliases = parts[1:]
    filtered = [alias for alias in aliases if alias.lower() != hostname.lower()]
    if len(filtered) == len(aliases):
        return raw
    if not filtered:
        return None
    rebuilt = f"{ip}\t" + "\t".join(filtered)
    if sep:
        rebuilt += f"\t# {comment.strip()}"
    return rebuilt


def update_hosts_file(ip: str, hostname: str = SERVICE_HOSTNAME) -> None:
    _validate_hosts_change(ip, hostname)
    path = hosts_path()
    original = path.read_text(encoding="utf-8", errors="replace")

    new_lines = []
    for raw in original.splitlines():
        updated = _remove_alias_from_hosts_line(raw, hostname)
        if updated is not None:
            new_lines.append(updated)

    # Keep the latest pre-change snapshot. This is intentional: it makes a
    # repair reversible without accumulating arbitrary backup files.
    backup = path.with_name(path.name + ".pulsia.bak")
    try:
        backup.write_text(original, encoding="utf-8")
    except OSError:
        pass

    new_lines.append(f"{ip}\t{hostname}\t# PULSIA Inventario Cliente")
    path.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")
    flush_dns_cache()


def flush_dns_cache() -> None:
    try:
        if platform.system() == "Windows":
            subprocess.run(["ipconfig", "/flushdns"], capture_output=True, timeout=8, check=False)
            return

        # Ubuntu 20.04 may use systemd-resolved; other distros may not.
        resolvectl = which("resolvectl")
        if resolvectl:
            subprocess.run([resolvectl, "flush-caches"], capture_output=True, timeout=8, check=False)
            return
        systemd_resolve = which("systemd-resolve")
        if systemd_resolve:
            subprocess.run([systemd_resolve, "--flush-caches"], capture_output=True, timeout=8, check=False)
    except (OSError, subprocess.SubprocessError):
        pass



def bundled_ca_exists() -> bool:
    path = bundled_ca_path()
    return path.exists() and path.is_file() and path.stat().st_size > 0


def bundled_ca_sha256() -> str:
    path = bundled_ca_path()
    if not bundled_ca_exists():
        return ""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest().upper()
    except Exception:
        return ""


def ca_is_installed() -> bool:
    """Best-effort check that the bundled root CA is trusted by this machine."""
    if not bundled_ca_exists():
        return False
    path = bundled_ca_path()
    if platform.system() == "Windows":
        escaped_path = str(path).replace("'", "''")
        ps = (
            "$ErrorActionPreference='SilentlyContinue';"
            f"$c=New-Object System.Security.Cryptography.X509Certificates.X509Certificate2('{escaped_path}');"
            "$m=Get-ChildItem Cert:\\LocalMachine\\Root | Where-Object {$_.Thumbprint -eq $c.Thumbprint};"
            "if($m){exit 0}else{exit 9}"
        )
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", ps],
                capture_output=True, timeout=10, check=False
            )
            return result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    target = Path("/usr/local/share/ca-certificates/PULSIA-Inventario-Root-CA.crt")
    try:
        return target.exists() and target.read_bytes() == path.read_bytes()
    except OSError:
        return False


def install_bundled_ca() -> list[str]:
    if not is_admin():
        raise PermissionError("Se requieren privilegios para instalar la CA PULSIA.")
    if not bundled_ca_exists():
        raise FileNotFoundError(f"No existe la CA del servidor: {bundled_ca_path()}")

    path = bundled_ca_path()
    actions: list[str] = []
    if platform.system() == "Windows":
        result = subprocess.run(
            [str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "certutil.exe"),
             "-addstore", "-f", "Root", str(path)],
            capture_output=True, text=True, timeout=25, check=False
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "certutil falló").strip())
        actions.append("CA raíz PULSIA instalada en Trusted Root Certification Authorities.")
        return actions

    target = Path("/usr/local/share/ca-certificates/PULSIA-Inventario-Root-CA.crt")
    target.write_bytes(path.read_bytes())
    target.chmod(0o644)
    updater = which("update-ca-certificates")
    if not updater:
        raise RuntimeError("update-ca-certificates no está disponible.")
    result = subprocess.run([updater], capture_output=True, text=True, timeout=30, check=False)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "update-ca-certificates falló").strip())
    actions.append("CA raíz PULSIA instalada en el almacén de confianza Linux.")
    return actions


def verify_https_system_trust(ip: str, hostname: str = SERVICE_HOSTNAME, timeout: float = 4.0) -> tuple[bool, str]:
    """Verify HTTPS using the operating-system/Python default trust store and SNI hostname."""
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((ip, 443), timeout=timeout) as raw:
            with ctx.wrap_socket(raw, server_hostname=hostname) as tls:
                tls.settimeout(timeout)
                tls.sendall((
                    f"GET / HTTP/1.1\r\nHost: {hostname}\r\n"
                    "User-Agent: PulsiaInventarioCliente/1.0\r\nConnection: close\r\n\r\n"
                ).encode("ascii"))
                data = tls.recv(4096).decode("iso-8859-1", errors="replace")
                if "HTTP/1.1" in data or "HTTP/2" in data or "location:" in data.lower():
                    return True, "HTTPS validado con la CA del sistema."
                return True, "TLS válido; respuesta HTTP recibida."
    except ssl.SSLCertVerificationError as exc:
        return False, f"Certificado no confiable: {exc}"
    except Exception as exc:
        return False, str(exc)


def renew_windows_network_if_dns_still_wrong(expected_ip: str, hostname: str = SERVICE_HOSTNAME) -> bool:
    """Use ipconfig /renew only as a last resort after hosts + flushdns remain inconsistent."""
    if platform.system() != "Windows" or dns_is_consistent(expected_ip, hostname):
        return True
    try:
        subprocess.run(["ipconfig", "/renew"], capture_output=True, timeout=45, check=False)
        flush_dns_cache()
        time.sleep(1.0)
    except (OSError, subprocess.SubprocessError):
        return False
    return dns_is_consistent(expected_ip, hostname)

def _run_text(cmd: list[str], timeout: int = 10) -> str:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        return ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def detect_local_caddy() -> list[dict]:
    """
    Best-effort inventory of local Caddy services/processes.
    We deliberately do NOT classify IIS/Apache/nginx as Caddy merely because
    they listen on 80/443.
    """
    found: list[dict] = []
    system = platform.system()

    if system == "Windows":
        # CIM gives us Name, DisplayName and PathName without requiring admin.
        ps = (
            "$ErrorActionPreference='SilentlyContinue';"
            "Get-CimInstance Win32_Service | "
            "Where-Object { $_.Name -match '(?i)caddy' -or "
            "$_.DisplayName -match '(?i)caddy' -or $_.PathName -match '(?i)caddy' } | "
            "ForEach-Object { '{0}|{1}|{2}|{3}|{4}' -f $_.Name,$_.DisplayName,$_.State,$_.StartMode,$_.PathName }"
        )
        output = _run_text(["powershell.exe", "-NoProfile", "-Command", ps])
        for line in output.splitlines():
            parts = line.split("|", 4)
            if len(parts) == 5:
                found.append({
                    "kind": "service",
                    "name": parts[0].strip(),
                    "display": parts[1].strip(),
                    "state": parts[2].strip(),
                    "start_mode": parts[3].strip(),
                    "path": parts[4].strip(),
                })

        output = _run_text(["tasklist", "/FO", "CSV", "/NH"])
        for line in output.splitlines():
            if "caddy" in line.lower():
                found.append({"kind": "process", "name": "caddy.exe", "detail": line.strip()})
        return found

    # Linux/systemd
    systemctl = which("systemctl")
    if systemctl:
        units = _run_text([systemctl, "list-unit-files", "--type=service", "--no-legend", "--no-pager"])
        for line in units.splitlines():
            fields = line.split()
            unit = fields[0] if fields else ""
            unit_file_state = fields[1] if len(fields) > 1 else "unknown"
            if "caddy" in unit.lower():
                state = _run_text([systemctl, "is-active", unit], timeout=5).splitlines()
                found.append({
                    "kind": "service",
                    "name": unit,
                    "state": state[0].strip() if state else "unknown",
                    "start_mode": unit_file_state,
                })

    pgrep = which("pgrep")
    if pgrep:
        output = _run_text([pgrep, "-af", "caddy"], timeout=5)
        for line in output.splitlines():
            # Avoid reporting this Python app or pgrep itself just because an
            # argument contains the word caddy.
            low = line.lower()
            if "pgrep" not in low and (" caddy" in low or "/caddy" in low):
                found.append({"kind": "process", "name": "caddy", "detail": line.strip()})
    return found



def caddy_item_is_conflict(item: dict) -> bool:
    if item.get("kind") == "process":
        return True
    state = str(item.get("state", "")).strip().lower()
    start_mode = str(item.get("start_mode", "")).strip().lower()
    active_states = {"running", "start pending", "start_pending", "active", "activating"}
    enabled_states = {"auto", "automatic", "enabled", "enabled-runtime"}
    return state in active_states or start_mode in enabled_states


def stop_disable_local_caddy() -> list[str]:
    """
    Stop/disable only services/processes positively identified as Caddy.
    Must be called with administrative/root privileges.
    """
    actions: list[str] = []
    if not is_admin():
        raise PermissionError("Se requieren privilegios para detener Caddy.")

    system = platform.system()
    detected = detect_local_caddy()

    if system == "Windows":
        service_names = []
        for item in detected:
            if caddy_item_is_conflict(item) and item.get("kind") == "service" and item.get("name"):
                name = item["name"]
                if name not in service_names:
                    service_names.append(name)

        for name in service_names:
            subprocess.run(["sc.exe", "stop", name], capture_output=True, timeout=15, check=False)
            subprocess.run(
                ["sc.exe", "config", name, "start=", "disabled"],
                capture_output=True, timeout=15, check=False
            )
            actions.append(f"Servicio Caddy detenido/deshabilitado: {name}")

        # Kill residual caddy.exe only; never kill arbitrary 80/443 owners.
        result = subprocess.run(
            ["taskkill", "/F", "/IM", "caddy.exe"],
            capture_output=True, text=True, timeout=10, check=False
        )
        if result.returncode == 0:
            actions.append("Procesos caddy.exe residuales finalizados.")
        return actions

    systemctl = which("systemctl")
    service_names = []
    for item in detected:
        if caddy_item_is_conflict(item) and item.get("kind") == "service" and item.get("name"):
            name = item["name"]
            if name not in service_names:
                service_names.append(name)

    if systemctl:
        for name in service_names:
            subprocess.run([systemctl, "stop", name], capture_output=True, timeout=15, check=False)
            subprocess.run([systemctl, "disable", name], capture_output=True, timeout=15, check=False)
            actions.append(f"Servicio Caddy detenido/deshabilitado: {name}")

    pkill = which("pkill")
    if pkill:
        # Exact executable-name match avoids killing arbitrary commands whose
        # arguments merely mention "caddy".
        result = subprocess.run([pkill, "-x", "caddy"], capture_output=True, timeout=10, check=False)
        if result.returncode == 0:
            actions.append("Procesos caddy residuales finalizados.")
    return actions


def repair_client_environment(ip: str, hostname: str = SERVICE_HOSTNAME) -> list[str]:
    """
    Privileged repair used after PULSIA has already been positively identified.
    """
    _validate_hosts_change(ip, hostname)
    if not is_admin():
        raise PermissionError("Se requieren privilegios para reparar el cliente.")

    actions: list[str] = []
    caddy = [item for item in detect_local_caddy() if caddy_item_is_conflict(item)]
    if caddy and not server_is_local_machine(ip):
        actions.extend(stop_disable_local_caddy())
    elif caddy and server_is_local_machine(ip):
        actions.append(
            "Caddy local detectado, pero no se detiene porque esta máquina coincide "
            "con la IP del servidor PULSIA."
        )

    if not dns_is_consistent(ip, hostname):
        previous_hosts = current_host_ip(hostname)
        previous_resolved = resolved_host_ips(hostname)
        update_hosts_file(ip, hostname)
        actions.append(
            f"DNS/hosts corregido: {hostname} -> {ip} "
            f"(hosts anterior={previous_hosts or 'sin entrada'}; "
            f"resolución anterior={','.join(previous_resolved) or 'sin respuesta'})."
        )
    else:
        actions.append(f"DNS/hosts correcto: {hostname} -> {ip}.")

    flush_dns_cache()
    if platform.system() == "Windows" and not dns_is_consistent(ip, hostname):
        actions.append("La resolución seguía siendo incoherente; se ejecuta ipconfig /renew como último recurso.")
        if not renew_windows_network_if_dns_still_wrong(ip, hostname):
            raise RuntimeError("La resolución DNS sigue siendo incoherente tras flushdns y renew.")
    return actions


def client_environment_needs_repair(ip: str, hostname: str = SERVICE_HOSTNAME) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not dns_is_consistent(ip, hostname):
        reasons.append(
            f"{hostname} no resuelve de forma consistente a {ip} "
            f"(hosts={current_host_ip(hostname) or '-'}; "
            f"resolver={','.join(resolved_host_ips(hostname)) or '-'})."
        )
    caddy = [item for item in detect_local_caddy() if caddy_item_is_conflict(item)]
    if caddy and not server_is_local_machine(ip):
        names = sorted({item.get("name", "Caddy") for item in caddy})
        reasons.append("Caddy local detectado: " + ", ".join(names))
    return bool(reasons), reasons


def _self_command(extra_args: list[str]) -> tuple[str, list[str]]:
    if getattr(sys, "frozen", False):
        return sys.executable, extra_args
    return sys.executable, [str(Path(__file__).resolve().parent / "main.py")] + extra_args



def request_ca_install(timeout: int = 45) -> bool:
    if not bundled_ca_exists():
        return False
    if ca_is_installed():
        return True
    if is_admin():
        try:
            install_bundled_ca()
            return ca_is_installed() if platform.system() == "Windows" else True
        except Exception:
            return False

    exe, args = _self_command(["--install-ca"])
    if platform.system() == "Windows":
        params = subprocess.list2cmdline(args)
        try:
            rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
        except Exception:
            return False
        if rc <= 32:
            return False
        deadline = time.time() + timeout
        while time.time() < deadline:
            if ca_is_installed():
                return True
            time.sleep(0.5)
        return False

    pkexec = which("pkexec")
    if not pkexec:
        return False
    try:
        result = subprocess.run([pkexec, exe] + args, timeout=timeout, check=False)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False

def request_client_repair(ip: str, hostname: str = SERVICE_HOSTNAME, timeout: int = 45) -> bool:
    """
    Elevate only if repair is actually required. The privileged child repairs
    hosts/DNS and stops local Caddy, then the parent verifies DNS resolution.
    """
    try:
        _validate_hosts_change(ip, hostname)
    except ValueError:
        return False

    needed, _ = client_environment_needs_repair(ip, hostname)
    if not needed:
        return True

    if is_admin():
        try:
            repair_client_environment(ip, hostname)
            return dns_is_consistent(ip, hostname)
        except (OSError, PermissionError, ValueError):
            return False

    exe, args = _self_command(["--repair-client", ip, hostname])

    if platform.system() == "Windows":
        params = subprocess.list2cmdline(args)
        try:
            rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
        except Exception:
            return False
        if rc <= 32:
            return False

        deadline = time.time() + timeout
        while time.time() < deadline:
            # The main correctness condition is DNS/hosts. Caddy may need a
            # couple of seconds to disappear after SCM acknowledges stop.
            if dns_is_consistent(ip, hostname):
                time.sleep(1.0)
                return True
            time.sleep(0.5)
        return False

    pkexec = which("pkexec")
    if not pkexec:
        return False
    try:
        result = subprocess.run([pkexec, exe] + args, timeout=timeout, check=False)
        return result.returncode == 0 and dns_is_consistent(ip, hostname)
    except (OSError, subprocess.SubprocessError):
        return False


# Backwards-compatible wrapper retained for callers/tests from previous versions.
def request_hosts_update(ip: str, hostname: str = SERVICE_HOSTNAME, timeout: int = 30) -> bool:
    return request_client_repair(ip, hostname, timeout=max(timeout, 30))
