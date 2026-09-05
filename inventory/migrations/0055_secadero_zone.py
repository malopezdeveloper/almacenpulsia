from django.db import migrations


def add_secadero(apps, schema_editor):
    Zone = apps.get_model('inventory', 'ProductionZone')
    zone, created = Zone.objects.get_or_create(
        code='secadero',
        defaults={'name': 'Secadero', 'position': 15, 'is_active': True},
    )
    if not created:
        changed = []
        if zone.name != 'Secadero':
            zone.name = 'Secadero'; changed.append('name')
        if not zone.is_active:
            zone.is_active = True; changed.append('is_active')
        if changed:
            zone.save(update_fields=changed)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [('inventory', '0054_pallet_shipping')]
    operations = [migrations.RunPython(add_secadero, noop_reverse)]
