from django.db import migrations


def normalize_stock(apps, schema_editor):
    CustomerOrder = apps.get_model('inventory', 'CustomerOrder')
    stock = CustomerOrder.objects.filter(
        name__iexact='stock', customer__isnull=True
    ).order_by('pk').first()
    if stock is None:
        # 0042 garantiza su creación. No inventamos otro pedido aquí si la
        # instalación está dañada; la comprobación de migraciones lo detectará.
        return
    changed = []
    if stock.name != 'STOCK':
        stock.name = 'STOCK'
        changed.append('name')
    if stock.status != 'open':
        stock.status = 'open'
        changed.append('status')
    if changed:
        stock.save(update_fields=changed)


class Migration(migrations.Migration):
    dependencies = [('inventory', '0042_repair_permanent_stock_order')]
    operations = [migrations.RunPython(normalize_stock, migrations.RunPython.noop)]
