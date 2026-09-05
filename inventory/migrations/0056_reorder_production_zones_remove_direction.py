from django.db import migrations


# Flujo principal visible primero. Las zonas no indicadas quedan detrás,
# y Reparaciones se fuerza al final de las zonas físicas.
MAIN_ORDER = [
    ('admision', 'Admisión'),
    ('auditoria', 'Auditoría'),
    ('pintura', 'Pintura'),
    ('teclados', 'Teclados'),
    ('secadero', 'Secadero'),
    ('montaje', 'Montaje'),
    ('calidad', 'Calidad'),
]


def normalize(value):
    return (value or '').strip().casefold().replace('ó', 'o').replace('í', 'i').replace('á', 'a').replace('é', 'e').replace('ú', 'u')


def reorder_zones(apps, schema_editor):
    Zone = apps.get_model('inventory', 'ProductionZone')
    zones = list(Zone.objects.all().order_by('position', 'pk'))

    # Dirección deja de ser una zona operativa. Se conserva el registro para
    # no romper trazabilidad histórica/FKs existentes, pero queda inactivo.
    for zone in zones:
        text = f'{normalize(zone.code)} {normalize(zone.name)}'
        if 'direccion' in text:
            if zone.is_active:
                zone.is_active = False
                zone.save(update_fields=['is_active'])

    active = list(Zone.objects.filter(is_active=True).order_by('position', 'pk'))
    used = set()
    position = 10

    for key, label in MAIN_ORDER:
        match = None
        for zone in active:
            if zone.pk in used:
                continue
            text = f'{normalize(zone.code)} {normalize(zone.name)}'
            if key in text:
                match = zone
                break
        if match:
            match.position = position
            match.save(update_fields=['position'])
            used.add(match.pk)
            position += 10

    # Resto de zonas, manteniendo su orden relativo anterior.
    for zone in active:
        if zone.pk in used:
            continue
        text = f'{normalize(zone.code)} {normalize(zone.name)}'
        if 'reparaciones' in text or 'reparacion' in text:
            continue
        zone.position = position
        zone.save(update_fields=['position'])
        used.add(zone.pk)
        position += 10

    # Reparaciones siempre cierra la lista de zonas físicas. Palet es un
    # destino logístico y la interfaz lo coloca justo antes de Reparaciones.
    for zone in active:
        text = f'{normalize(zone.code)} {normalize(zone.name)}'
        if 'reparaciones' in text or 'reparacion' in text:
            zone.position = 9990
            zone.save(update_fields=['position'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [('inventory', '0055_secadero_zone')]
    operations = [migrations.RunPython(reorder_zones, noop_reverse)]
