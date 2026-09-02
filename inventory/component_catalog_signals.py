from django.db import transaction
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from .models import Reservation, InventoryRecord, RecordMovement
from .order_models import ComponentReservation

def _catalog(record):
 try:record.table.component_catalog;return True
 except Exception:return False
def _save_trace(record,reservation_date=None,destination_sn=None):
 if record is None:return
 data=dict(record.data or {})
 if 'reservation_date' in data or record.table.inventory_fields.filter(key='reservation_date').exists():data['reservation_date']=reservation_date or ''
 if 'destination_sn' in data or record.table.inventory_fields.filter(key='destination_sn').exists():data['destination_sn']=destination_sn or ''
 record.data=data;record.save(update_fields=['data','updated_at'])
@receiver(pre_save,sender=Reservation)
def remember_reservation_status(sender,instance,**kwargs):
 if instance.pk:
  instance._previous_status=Reservation.objects.filter(pk=instance.pk).values_list('status',flat=True).first()
 else:instance._previous_status=None
@receiver(post_save,sender=Reservation)
def sync_inventory_reservation(sender,instance,created=False,**kwargs):
 record=instance.record
 if not _catalog(record):return
 if created and instance.status in {'pending','accepted'}:
  with transaction.atomic():
   locked=InventoryRecord.objects.select_for_update().get(pk=record.pk);data=dict(locked.data or {});qty=max(0,int(data.get('quantity') or 0))
   if qty>0:data['quantity']=str(qty-1);locked.data=data;locked.status='available' if qty-1>0 else 'delivered';locked.save(update_fields=['data','status','updated_at']);RecordMovement.objects.create(record=locked,movement_type='reserve',destination_sn=instance.destination_sn,reason=f'Reserva genérica: -1 unidad. Quedan {qty-1}.',registered_by=instance.requested_by)
 if getattr(instance,'_previous_status',None) in {'pending','accepted'} and instance.status in {'rejected','cancelled'}:
  with transaction.atomic():
   locked=InventoryRecord.objects.select_for_update().get(pk=record.pk);data=dict(locked.data or {});data['quantity']=str(int(data.get('quantity') or 0)+1);locked.data=data;locked.status='available';locked.save(update_fields=['data','status','updated_at']);RecordMovement.objects.create(record=locked,movement_type='return',reason='Reserva genérica cancelada: +1 unidad.',registered_by=instance.requested_by)
 if instance.status in {'pending','accepted','delivered'}:_save_trace(record,instance.requested_at.date().isoformat() if instance.requested_at else '',instance.destination_sn)
 elif instance.status in {'rejected','cancelled'}:_save_trace(record,'','')
@receiver(post_save,sender=ComponentReservation)
def sync_component_reservation(sender,instance,**kwargs):
 record=getattr(instance.component,'inventory_record',None)
 if record is None or not _catalog(record):return
 if instance.status in {'active','installed','confirmed'}:_save_trace(record,instance.reserved_at.date().isoformat() if instance.reserved_at else '',instance.unit_serial_number)
