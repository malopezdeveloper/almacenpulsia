from django.conf import settings
from django.db import migrations


def repair_stock_order(apps, schema_editor):
    CustomerOrder = apps.get_model('inventory', 'CustomerOrder')
    User = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))

    # Si ya existe el STOCK técnico correcto, lo normalizamos y terminamos.
    stock = CustomerOrder.objects.filter(name__iexact='stock', customer__isnull=True).order_by('pk').first()
    if stock:
        changed = []
        if stock.name != 'STOCK':
            stock.name = 'STOCK'; changed.append('name')
        if stock.status != 'open':
            stock.status = 'open'; changed.append('status')
        if changed:
            stock.save(update_fields=changed)
        return

    creator_id = User.objects.order_by('pk').values_list('pk', flat=True).first()
    if creator_id is None:
        raise RuntimeError('No se puede crear STOCK porque todavía no existe ningún usuario del sistema.')

    CustomerOrder.objects.create(
        name='STOCK', customer_id=None,
        brand='', model='', lot='', processor='', ram='', disk='',
        status='open', visual_family='green', created_by_id=creator_id,
    )


class Migration(migrations.Migration):
    dependencies = [('inventory', '0041_board_priorities_and_stock_order')]
    operations = [migrations.RunPython(repair_stock_order, migrations.RunPython.noop)]
