import re
from collections import OrderedDict

from django import template

register = template.Library()

_CAPACITY_RE = re.compile(r"(\d+(?:[\.,]\d+)?)\s*(TB|GB|MB)\b", re.IGNORECASE)
_MULTIPLIER_RE = re.compile(r"(?:x|×)\s*(\d+)\b", re.IGNORECASE)


def _to_gb(number, unit):
    try:
        value = float(str(number).replace(",", "."))
    except (TypeError, ValueError):
        return None
    unit = str(unit).upper()
    if unit == "TB":
        value *= 1024
    elif unit == "MB":
        value /= 1024
    return value


def _format_gb(value):
    if value is None:
        return ""
    if abs(value - round(value)) < 0.01:
        return f"{int(round(value))} GB"
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{text} GB"


def capacity_mask(value):
    """Máscara SOLO de presentación para RAM/disco.

    El valor original no se modifica. Extrae la capacidad de cada dispositivo
    y agrupa módulos iguales: "4 GB + 4 GB" -> "4 GB x 2".
    Los informes pueden seguir usando el texto técnico original almacenado.
    """
    raw = " ".join(str(value or "").strip().split())
    if not raw:
        return ""

    # AIKEN separa los dispositivos auditados con " + ". Cada bloque conserva
    # fabricante/modelo/Info/Size/Speed, por eso elegimos la última capacidad
    # con unidad de cada dispositivo (normalmente el campo Size).
    parts = re.split(r"\s+\+\s+", raw)
    capacities = []
    for part in parts:
        matches = list(_CAPACITY_RE.finditer(part))
        if not matches:
            continue
        match = matches[-1]
        gb = _to_gb(match.group(1), match.group(2))
        if gb is None:
            continue
        multiplier = 1
        if len(parts) == 1:
            mult_match = _MULTIPLIER_RE.search(part[match.end():])
            if mult_match:
                multiplier = max(1, int(mult_match.group(1)))
        capacities.extend([gb] * multiplier)

    if not capacities:
        # No inventamos una capacidad cuando el dato no lleva una unidad
        # reconocible; mostramos el original para no ocultar información útil.
        return raw

    grouped = OrderedDict()
    for gb in capacities:
        key = round(gb, 4)
        grouped[key] = grouped.get(key, 0) + 1

    display = []
    for gb, count in grouped.items():
        item = _format_gb(gb)
        display.append(f"{item} x {count}" if count > 1 else item)
    return " + ".join(display)


@register.filter
def gb_capacity(value):
    return capacity_mask(value)


@register.filter
def get_item(mapping, key):
    if not isinstance(mapping, dict):
        return ""
    value = mapping.get(key, "")
    if value is True:
        return "Sí"
    if value is False:
        return "No"
    return value
