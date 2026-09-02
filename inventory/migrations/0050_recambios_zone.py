from django.db import migrations


def create_recambios_zone(apps, schema_editor):
    ProductionZone = apps.get_model('inventory', 'ProductionZone')
    name = 'Recambios (Almacén/Bodega)'
    zone = ProductionZone.objects.filter(name__iexact=name).first()
    if zone:
        changed = []
        if not zone.is_active:
            zone.is_active = True
            changed.append('is_active')
        if changed:
            zone.save(update_fields=changed)
        return
    max_position = 0
    for value in ProductionZone.objects.values_list('position', flat=True):
        max_position = max(max_position, value or 0)
    ProductionZone.objects.create(name=name, position=max_position + 10, is_active=True)


class Migration(migrations.Migration):
    dependencies = [('inventory', '0049_reconditioning_cycles_and_accumulated_reservations')]

    operations = [migrations.RunPython(create_recambios_zone, migrations.RunPython.noop)]
