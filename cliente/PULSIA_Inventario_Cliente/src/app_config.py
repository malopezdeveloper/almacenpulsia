from __future__ import annotations

import json
import os
import platform
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SERVICE_HOSTNAME = "almacen"
SERVICE_PORT = 443
CONFIG_VERSION = 3


def bundle_root() -> Path:
    """Root of the portable client, both in source and PyInstaller builds."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def bundled_server_config_path() -> Path:
    return bundle_root() / "servidor_cliente.ini"


def bundled_ca_path() -> Path:
    return bundle_root() / "certificados" / "PULSIA-Inventario-Root-CA.crt"


def load_deployment_ini() -> dict[str, str]:
    path = bundled_server_config_path()
    data: dict[str, str] = {}
    if not path.exists():
        return data
    try:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            data[key.strip().upper()] = value.strip()
    except OSError:
        return {}
    return data


def _secure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    if platform.system() != "Windows":
        try:
            path.chmod(0o700)
        except OSError:
            pass
    return path


def app_data_dir() -> Path:
    if platform.system() == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        path = base / "PULSIA" / "InventarioCliente"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        path = base / "PULSIA" / "InventarioCliente"
    return _secure_directory(path)


CONFIG_PATH = app_data_dir() / "config.json"
WEB_PROFILE_PATH = app_data_dir() / "webprofile"


@dataclass
class ServerInfo:
    ip: str
    mac: str = ""
    reverse_hostname: str = ""
    service_hostname: str = SERVICE_HOSTNAME
    port: int = SERVICE_PORT
    certificate_sha256: str = ""
    last_seen: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "ServerInfo":
        allowed = set(cls.__dataclass_fields__.keys())
        return cls(**{k: v for k, v in data.items() if k in allowed})

    def touch(self) -> None:
        self.last_seen = datetime.now(timezone.utc).isoformat()


@dataclass
class UserPreferences:
    username: str = ""
    remember_username: bool = False
    remember_password: bool = False
    keep_session: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "UserPreferences":
        allowed = set(cls.__dataclass_fields__.keys())
        return cls(**{k: v for k, v in data.items() if k in allowed})


@dataclass
class AppConfig:
    server: Optional[ServerInfo] = None
    user: UserPreferences | None = None

    def __post_init__(self) -> None:
        if self.user is None:
            self.user = UserPreferences()


def _deployment_server() -> Optional[ServerInfo]:
    ini = load_deployment_ini()
    ip = ini.get("SERVER_IP", "").strip()
    if not ip:
        return None
    return ServerInfo(
        ip=ip,
        mac=ini.get("SERVER_MAC", "").strip().upper(),
        reverse_hostname=ini.get("SERVER_SYSTEM_HOSTNAME", "").strip(),
        service_hostname=ini.get("SERVER_HOST", SERVICE_HOSTNAME) or SERVICE_HOSTNAME,
        port=int(ini.get("SERVER_PORT", SERVICE_PORT) or SERVICE_PORT),
        certificate_sha256=ini.get("CA_SHA256", ""),
    )


def load_config() -> AppConfig:
    config = AppConfig(server=_deployment_server())
    if not CONFIG_PATH.exists():
        return config
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        server = ServerInfo.from_dict(data["server"]) if data.get("server") else config.server
        user = UserPreferences.from_dict(data.get("user", {}))
        return AppConfig(server=server, user=user)
    except (OSError, ValueError, TypeError, KeyError):
        return config


def save_config(config: AppConfig) -> None:
    payload = {
        "version": CONFIG_VERSION,
        "server": asdict(config.server) if config.server else None,
        "user": asdict(config.user),
    }
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    if platform.system() != "Windows":
        try:
            tmp.chmod(0o600)
        except OSError:
            pass
    os.replace(tmp, CONFIG_PATH)
    if platform.system() != "Windows":
        try:
            CONFIG_PATH.chmod(0o600)
        except OSError:
            pass
