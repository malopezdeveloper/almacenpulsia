from django.conf import settings
from django.db import migrations


def create_warranty_system(apps, schema_editor):
    Role = apps.get_model('inventory', 'BusinessRole')
    Order = apps.get_model('inventory', 'CustomerOrder')
    User = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))

    Role.objects.update_or_create(
        code='responsable-garantias',
        defaults={
            'name': 'Responsable de Garantías',
            'permissions': ['warranty.manage', 'warranty.intake'],
            'active': True,
            'protected': True,
        },
    )

    order = Order.objects.filter(name__iexact='GARANTÍAS', customer__isnull=True).order_by('pk').first()
    if order:
        changed=[]
        if order.status != 'open': order.status='open'; changed.append('status')
        if order.closed_at is not None: order.closed_at=None; changed.append('closed_at')
        if changed: order.save(update_fields=changed)
        return

    creator = User.objects.filter(is_superuser=True).order_by('pk').first() or User.objects.order_by('pk').first()
    if creator:
        Order.objects.create(name='GARANTÍAS', customer=None, status='open', visual_family='brown', created_by=creator)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [('inventory', '0056_reorder_production_zones_remove_direction')]
    operations = [migrations.RunPython(create_warranty_system, noop)]
