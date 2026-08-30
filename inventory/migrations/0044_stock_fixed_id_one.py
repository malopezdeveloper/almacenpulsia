from django.db import migrations


def normalize_stock(apps, schema_editor):
    """STOCK es el primer pedido lógico, no necesita un PK concreto."""
    CustomerOrder = apps.get_model('inventory', 'CustomerOrder')
    stock = (
        CustomerOrder.objects
        .filter(name__iexact='stock', customer__isnull=True)
        .order_by('pk')
        .first()
    )
    if stock is None:
        raise RuntimeError('No existe el pedido permanente STOCK.')

    changed = []
    if stock.name != 'STOCK':
        stock.name = 'STOCK'; changed.append('name')
    if stock.status != 'open':
        stock.status = 'open'; changed.append('status')
    if stock.closed_at is not None:
        stock.closed_at = None; changed.append('closed_at')
    if stock.closed_by_id is not None:
        stock.closed_by_id = None; changed.append('closed_by')
    if changed:
        stock.save(update_fields=changed)


class Migration(migrations.Migration):
    dependencies = [('inventory', '0043_stock_first_order')]
    operations = [migrations.RunPython(normalize_stock, migrations.RunPython.noop)]
