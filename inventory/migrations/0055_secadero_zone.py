from django.db import migrations


def add_secadero(apps, schema_editor):
    Zone = apps.get_model('inventory', 'ProductionZone')
    zone = Zone.objects.filter(code='secadero').first() or Zone.objects.filter(name__iexact='Secadero').first()
    if zone is None:
        Zone.objects.create(code='secadero', name='Secadero', position=15, is_active=True)
        return
    changed = []
    if zone.code != 'secadero' and not Zone.objects.exclude(pk=zone.pk).filter(code='secadero').exists():
        zone.code = 'secadero'; changed.append('code')
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
