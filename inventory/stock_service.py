from django.contrib.auth import get_user_model
from django.db import transaction

from .order_models import CustomerOrder


def ensure_permanent_stock_order():
    """Garantiza que exista el pedido técnico permanente STOCK.

    Se ejecuta al arrancar la aplicación, además de las migraciones, para que
    STOCK no dependa de una instalación concreta ni pueda desaparecer de forma
    permanente por una manipulación accidental de la base de datos.
    """
    stock = CustomerOrder.objects.filter(
        name__iexact='stock', customer__isnull=True
    ).order_by('pk').first()

    if stock is not None:
        changed = []
        if stock.name != 'STOCK':
            stock.name = 'STOCK'
            changed.append('name')
        if stock.status != 'open':
            stock.status = 'open'
            changed.append('status')
        if changed:
            stock.save(update_fields=changed)
        return stock

    User = get_user_model()
    creator = User.objects.order_by('pk').first()
    if creator is None:
        return None

    with transaction.atomic():
        stock = CustomerOrder.objects.filter(
            name__iexact='stock', customer__isnull=True
        ).order_by('pk').first()
        if stock is not None:
            return stock

        return CustomerOrder.objects.create(
            name='STOCK',
            customer_id=None,
            brand='',
            model='',
            lot='',
            processor='',
            ram='',
            disk='',
            status='open',
            visual_family='green',
            created_by=creator,
        )
