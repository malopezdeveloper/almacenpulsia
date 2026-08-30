from django.db import migrations


def _copy_order(CustomerOrder, source, target_pk):
    target = CustomerOrder.objects.create(
        pk=target_pk,
        name=source.name,
        customer_id=source.customer_id,
        brand=source.brand,
        model=source.model,
        lot=source.lot,
        processor=source.processor,
        ram=source.ram,
        disk=source.disk,
        status=source.status,
        visual_family=source.visual_family,
        closed_at=source.closed_at,
        closed_by_id=source.closed_by_id,
        created_by_id=source.created_by_id,
    )
    CustomerOrder.objects.filter(pk=target.pk).update(created_at=source.created_at)
    return target


def _move_relations(apps, old_pk, new_pk):
    OrderUnit = apps.get_model('inventory', 'OrderUnit')
    OrderStatusEvent = apps.get_model('inventory', 'OrderStatusEvent')
    BoardPriority = apps.get_model('inventory', 'BoardPriority')
    OrderUnit.objects.filter(order_id=old_pk).update(order_id=new_pk)
    OrderStatusEvent.objects.filter(order_id=old_pk).update(order_id=new_pk)
    BoardPriority.objects.filter(order_id=old_pk).update(order_id=new_pk)


def force_stock_id_one(apps, schema_editor):
    CustomerOrder = apps.get_model('inventory', 'CustomerOrder')
    stock = CustomerOrder.objects.filter(name__iexact='stock', customer__isnull=True).order_by('pk').first()
    if stock is None:
        raise RuntimeError('No existe el pedido permanente STOCK.')

    # Ya está en su identificador reservado: sólo normalizarlo.
    if stock.pk == 1:
        CustomerOrder.objects.filter(pk=1).update(name='STOCK', status='open', closed_at=None, closed_by_id=None)
        return

    # Si una instalación antigua ya utilizó el ID 1 para un pedido normal,
    # lo trasladamos primero a un ID libre conservando todas sus relaciones.
    occupied = CustomerOrder.objects.filter(pk=1).first()
    if occupied is not None:
        new_pk = (CustomerOrder.objects.order_by('-pk').values_list('pk', flat=True).first() or 1) + 1
        _copy_order(CustomerOrder, occupied, new_pk)
        _move_relations(apps, 1, new_pk)
        CustomerOrder.objects.filter(pk=1).delete()

    old_stock_pk = stock.pk
    new_stock = _copy_order(CustomerOrder, stock, 1)
    CustomerOrder.objects.filter(pk=new_stock.pk).update(
        name='STOCK', customer_id=None, status='open', closed_at=None, closed_by_id=None
    )
    _move_relations(apps, old_stock_pk, 1)
    CustomerOrder.objects.filter(pk=old_stock_pk).delete()


class Migration(migrations.Migration):
    dependencies = [('inventory', '0043_stock_first_order')]
    operations = [migrations.RunPython(force_stock_id_one, migrations.RunPython.noop)]
