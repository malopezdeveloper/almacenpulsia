from __future__ import annotations

SERVICE_NAME = "PULSIA Inventario Cliente"

try:
    import keyring
except Exception:
    keyring = None

def keyring_available() -> bool:
    if keyring is None:
        return False
    try:
        backend = keyring.get_keyring()
        priority = getattr(backend, "priority", 0)
        identity = f"{backend.__class__.__module__}.{backend.__class__.__name__}".lower()
        insecure_markers = ("plaintext", "keyrings.alt.file", "fail.keyring", "null")
        return bool(priority > 0 and not any(marker in identity for marker in insecure_markers))
    except Exception:
        return False

def save_password(username: str, password: str) -> bool:
    if not username or not password or not keyring_available():
        return False
    try:
        keyring.set_password(SERVICE_NAME, username, password)
        return True
    except Exception:
        return False

def load_password(username: str) -> str:
    if not username or not keyring_available():
        return ""
    try:
        return keyring.get_password(SERVICE_NAME, username) or ""
    except Exception:
        return ""

def delete_password(username: str) -> None:
    if not username or not keyring_available():
        return
    try:
        keyring.delete_password(SERVICE_NAME, username)
    except Exception:
        pass
