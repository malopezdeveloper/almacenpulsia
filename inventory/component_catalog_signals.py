from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Reservation
from .order_models import ComponentReservation


def _save_trace(record, reservation_date=None, destination_sn=None):
    if record is None:
        return
    data = dict(record.data or {})
    if 'reservation_date' in data or record.table.inventory_fields.filter(key='reservation_date').exists():
        data['reservation_date'] = reservation_date or ''
    if 'destination_sn' in data or record.table.inventory_fields.filter(key='destination_sn').exists():
        data['destination_sn'] = destination_sn or ''
    record.data = data
    record.save(update_fields=['data', 'updated_at'])


@receiver(post_save, sender=Reservation)
def sync_inventory_reservation(sender, instance, **kwargs):
    try:
        instance.record.table.component_catalog
    except Exception:
        return
    if instance.status in {'pending', 'accepted', 'delivered'}:
        date_value = instance.requested_at.date().isoformat() if instance.requested_at else ''
        _save_trace(instance.record, date_value, instance.destination_sn)
    elif instance.status in {'rejected', 'cancelled'}:
        _save_trace(instance.record, '', '')


@receiver(post_save, sender=ComponentReservation)
def sync_component_reservation(sender, instance, **kwargs):
    record = getattr(instance.component, 'inventory_record', None)
    if record is None:
        return
    try:
        record.table.component_catalog
    except Exception:
        return
    if instance.status in {'active', 'installed', 'confirmed'}:
        date_value = instance.reserved_at.date().isoformat() if instance.reserved_at else ''
        _save_trace(record, date_value, instance.unit_serial_number)
    elif instance.status == 'cancelled':
        _save_trace(record, '', '')
