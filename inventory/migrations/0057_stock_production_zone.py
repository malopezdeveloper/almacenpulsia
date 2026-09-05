from django.db import migrations


def add_stock_zone(apps, schema_editor):
    Zone = apps.get_model('inventory', 'ProductionZone')
    zone = Zone.objects.filter(code__iexact='stock').first()
    if zone is None:
        zone = Zone.objects.filter(name__iexact='Stock').first()
    if zone is None:
        Zone.objects.create(code='stock', name='Stock', is_active=True, position=80)
    else:
        changed = []
        if zone.code != 'stock':
            zone.code = 'stock'; changed.append('code')
        if zone.name != 'Stock':
            zone.name = 'Stock'; changed.append('name')
        if not zone.is_active:
            zone.is_active = True; changed.append('is_active')
        if zone.position != 80:
            zone.position = 80; changed.append('position')
        if changed:
            zone.save(update_fields=changed)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [('inventory', '0056_reorder_production_zones_remove_direction')]
    operations = [migrations.RunPython(add_stock_zone, noop_reverse)]
