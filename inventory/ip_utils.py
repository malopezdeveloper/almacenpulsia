import ipaddress


def is_protected_local_ip(value):
    """True para direcciones loopback locales que nunca deben poder bloquear la app."""
    try:
        return ipaddress.ip_address((value or "").strip()).is_loopback
    except ValueError:
        return False
