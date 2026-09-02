from django.conf import settings
from django.db import models,transaction
from django.utils import timezone

class BusinessRole(models.Model):
 name=models.CharField(max_length=80,unique=True);code=models.SlugField(max_length=80,unique=True);permissions=models.JSONField(default=list,blank=True);active=models.BooleanField(default=True);protected=models.BooleanField(default=False);created_at=models.DateTimeField(auto_now_add=True);updated_at=models.DateTimeField(auto_now=True)
 def __str__(self):return self.name
class BusinessRoleAssignment(models.Model):
 user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name='pulsia_role_assignments');role=models.ForeignKey(BusinessRole,on_delete=models.PROTECT,related_name='assignments');created_at=models.DateTimeField(auto_now_add=True)
 class Meta:constraints=[models.UniqueConstraint(fields=['user','role'],name='unique_pulsia_user_role')]
class Customer(models.Model):
 name=models.CharField(max_length=180,unique=True,db_index=True);phone=models.CharField(max_length=80,blank=True);email=models.EmailField(blank=True);address=models.CharField(max_length=300,blank=True);delivery_point=models.CharField(max_length=300,blank=True);contact=models.CharField(max_length=180,blank=True);observations=models.TextField(blank=True);active=models.BooleanField(default=True)
 def __str__(self):return self.name
class Supplier(models.Model):
 name=models.CharField(max_length=180,unique=True,db_index=True);phone=models.CharField(max_length=80,blank=True);email=models.EmailField(blank=True);address=models.CharField(max_length=300,blank=True);delivery_point=models.CharField(max_length=300,blank=True);contact=models.CharField(max_length=180,blank=True);observations=models.TextField(blank=True);active=models.BooleanField(default=True)
 def __str__(self):return self.name
class ComponentType(models.Model):
 name=models.CharField(max_length=160,unique=True,db_index=True);active=models.BooleanField(default=True,db_index=True);created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='component_types_created');created_at=models.DateTimeField(auto_now_add=True)
 def __str__(self):return self.name
class PhysicalUnit(models.Model):
 serial_number=models.CharField(max_length=180,unique=True,db_index=True);brand=models.CharField(max_length=160,blank=True);model=models.CharField(max_length=180,blank=True);processor=models.CharField(max_length=500,blank=True);ram=models.CharField(max_length=500,blank=True);disk=models.CharField(max_length=500,blank=True);created_at=models.DateTimeField(auto_now_add=True)
 def __str__(self):return self.serial_number
class CustomerOrder(models.Model):
 STATUS=[('open','Abierto'),('closed','Cerrado')];VISUAL=[('green','Verde'),('brown','Marrón')]
 name=models.CharField(max_length=180,db_index=True);customer=models.ForeignKey(Customer,on_delete=models.PROTECT,related_name='orders',null=True,blank=True);brand=models.CharField(max_length=160,blank=True);model=models.CharField(max_length=180,blank=True);lot=models.CharField(max_length=160,blank=True,db_index=True);processor=models.CharField(max_length=500,blank=True);ram=models.CharField(max_length=500,blank=True);disk=models.CharField(max_length=500,blank=True);status=models.CharField(max_length=12,choices=STATUS,default='open',db_index=True);visual_family=models.CharField(max_length=12,choices=VISUAL,default='green');closed_at=models.DateTimeField(null=True,blank=True);closed_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='customer_orders_closed');created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='customer_orders_created');created_at=models.DateTimeField(auto_now_add=True)
 def __str__(self):return f'{self.pk} · {self.name}'
class OrderUnit(models.Model):
 order=models.ForeignKey(CustomerOrder,on_delete=models.CASCADE,related_name='units');physical_unit=models.ForeignKey(PhysicalUnit,on_delete=models.PROTECT,related_name='order_cycles');serial_number=models.CharField(max_length=180,db_index=True);aiken_lot=models.CharField(max_length=160,blank=True,db_index=True);aiken_unit_id=models.CharField(max_length=180,blank=True,db_index=True);brand=models.CharField(max_length=160,blank=True);model=models.CharField(max_length=180,blank=True);processor=models.CharField(max_length=500,blank=True);ram=models.CharField(max_length=500,blank=True);disk=models.CharField(max_length=500,blank=True);imported_at=models.DateTimeField(auto_now_add=True)
 class Meta:indexes=[models.Index(fields=['physical_unit','-imported_at'],name='orderunit_cycle_idx')]
 def save(self,*a,**k):
  if not self.physical_unit_id:
   sn=(self.serial_number or '').strip()
   if not sn:raise ValueError('La unidad necesita un número de serie.')
   defaults={'brand':self.brand,'model':self.model,'processor':self.processor,'ram':self.ram,'disk':self.disk};self.physical_unit,_=PhysicalUnit.objects.get_or_create(serial_number=sn,defaults=defaults)
  self.serial_number=self.physical_unit.serial_number;return super().save(*a,**k)
 def __str__(self):return self.serial_number
class OrderStatusEvent(models.Model):
 ACTIONS=[('closed','Cerrado'),('reopened','Reabierto')];order=models.ForeignKey(CustomerOrder,on_delete=models.CASCADE,related_name='status_events');action=models.CharField(max_length=12,choices=ACTIONS);user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='order_status_events');created_at=models.DateTimeField(auto_now_add=True)
 class Meta:ordering=('-created_at','-pk')
class Component(models.Model):
 STATUS=[('active','Disponible'),('reserved','Reservado'),('installed','Instalado'),('low','Baja')];component_type=models.CharField(max_length=160,db_index=True);component_kind=models.ForeignKey(ComponentType,on_delete=models.PROTECT,null=True,blank=True,related_name='components');supplier=models.ForeignKey(Supplier,on_delete=models.PROTECT,related_name='components',null=True,blank=True);reference=models.CharField(max_length=200,blank=True,db_index=True);inventory_record=models.OneToOneField('inventory.InventoryRecord',on_delete=models.PROTECT,null=True,blank=True,related_name='managed_component');date=models.DateField(default=timezone.localdate);price=models.DecimalField(max_digits=12,decimal_places=2,default=0);observations=models.TextField(blank=True);status=models.CharField(max_length=16,choices=STATUS,default='active',db_index=True)
 def save(self,*a,**k):
  if self.component_kind_id:self.component_type=self.component_kind.name
  return super().save(*a,**k)
 def __str__(self):return self.reference or f'{self.component_type} #{self.pk}'
class Repair(models.Model):
 unit=models.ForeignKey(OrderUnit,on_delete=models.PROTECT,related_name='repairs');repair_type=models.CharField(max_length=160,db_index=True);component_type=models.ForeignKey(ComponentType,on_delete=models.PROTECT,null=True,blank=True,related_name='repairs');observations=models.TextField(blank=True);created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='repairs_created');created_at=models.DateTimeField(auto_now_add=True)
 def __str__(self):return f'{self.unit.serial_number} · {self.repair_type}'
class ProcurementAlert(models.Model):
 STATUS=[('open','Abierta'),('resolved','Resuelta')];repair=models.ForeignKey(Repair,on_delete=models.CASCADE,related_name='procurement_alerts',null=True,blank=True);unit=models.ForeignKey(OrderUnit,on_delete=models.CASCADE,related_name='procurement_alerts',null=True,blank=True);component_type=models.ForeignKey(ComponentType,on_delete=models.PROTECT,null=True,blank=True,related_name='procurement_alerts');message=models.CharField(max_length=500);status=models.CharField(max_length=12,choices=STATUS,default='open',db_index=True);created_at=models.DateTimeField(auto_now_add=True,db_index=True);resolved_at=models.DateTimeField(null=True,blank=True)
class ComponentReservation(models.Model):
 STATUS=[('active','Reservado'),('installed','Instalado pendiente de confirmación'),('confirmed','Reparación confirmada'),('cancelled','Cancelada')];repair=models.ForeignKey(Repair,on_delete=models.PROTECT,related_name='component_reservations',null=True,blank=True);unit=models.ForeignKey(OrderUnit,on_delete=models.PROTECT,related_name='component_reservations',null=True,blank=True);component=models.ForeignKey(Component,on_delete=models.PROTECT,related_name='reservations');technician=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='component_reservations');installed_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='component_installations',null=True,blank=True);unit_serial_number=models.CharField(max_length=180,db_index=True);status=models.CharField(max_length=16,choices=STATUS,default='active',db_index=True);reserved_at=models.DateTimeField(auto_now_add=True);installed_at=models.DateTimeField(null=True,blank=True);resolved_at=models.DateTimeField(null=True,blank=True);observations=models.TextField(blank=True)
 def save(self,*a,**k):
  if self.unit_id:self.unit_serial_number=self.unit.serial_number
  return super().save(*a,**k)
 def _is_accumulated(self,record):
  if not record:return False
  try:record.table.component_catalog;return True
  except Exception:return False
 def cancel(self):
  if self.status!='active':return
  from .models import RecordMovement
  with transaction.atomic():
   record=self.component.inventory_record
   self.status='cancelled';self.resolved_at=timezone.now();self.save(update_fields=['status','resolved_at'])
   if self._is_accumulated(record):
    record=record.__class__.objects.select_for_update().get(pk=record.pk);data=dict(record.data or {});data['quantity']=str(int(data.get('quantity') or 0)+1);record.data=data;record.status='available';record.current_sn='';record.current_technician='';record.save(update_fields=['data','status','current_sn','current_technician','updated_at']);self.component.status='active';self.component.save(update_fields=['status']);RecordMovement.objects.create(record=record,movement_type='return',reason=f'Reserva cancelada para {self.unit_serial_number}; +1 devuelto al lote.',registered_by=self.technician);return
   self.component.status='active';self.component.save(update_fields=['status'])
   if record:
    record.status='available';record.current_sn='';record.current_technician='';data=dict(record.data or {})
    for field in record.table.inventory_fields.all():
     key=field.key.casefold();name=field.name.casefold()
     if field.is_destination_sn or field.is_technician or field.field_type=='date' or 'fecha' in key or 'fecha' in name or 'tecnic' in key or 'tecnic' in name or key=='sn':data[field.key]=''
    record.data=data;record.save(update_fields=['status','current_sn','current_technician','data','updated_at']);RecordMovement.objects.create(record=record,movement_type='return',reason=f'Reserva cancelada para {self.unit_serial_number}; componente devuelto a disponible.',registered_by=self.technician)
 def install(self,user):
  if self.status!='active':return self.repair
  from .models import RecordMovement
  from .component_flow_models import Installation
  with transaction.atomic():
   repair=Repair.objects.create(unit=self.unit,repair_type=self.component.component_type,component_type=self.component.component_kind,created_by=user,observations=self.observations);self.repair=repair;self.installed_by=user;self.installed_at=timezone.now();self.status='installed';self.save(update_fields=['repair','installed_by','installed_at','status']);record=self.component.inventory_record;accumulated=self._is_accumulated(record)
   if not accumulated:self.component.status='installed';self.component.save(update_fields=['status'])
   source='reservation'
   try:
    if hasattr(self,'allocation'):source=self.allocation.source
   except Exception:pass
   Installation.objects.create(reservation=self,unit=self.unit,component=self.component,inventory_record=record,technician=user,source=source,unit_serial_number=self.unit_serial_number,component_reference=self.component.reference,component_type=self.component.component_type,inventory_table_name=record.table.name if record else '',inventory_internal_id=record.internal_id if record else '',metadata={'reservation_id':self.pk,'reserved_by_id':self.technician_id,'repair_id':repair.pk,'order_id':self.unit.order_id})
   if record:
    if accumulated:
     data=dict(record.data or {});remaining=int(data.get('quantity') or 0);record.status='available' if remaining>0 else 'delivered';self.component.status='active' if remaining>0 else 'low';self.component.save(update_fields=['status']);RecordMovement.objects.create(record=record,movement_type='assign',technician_name=user.get_username(),destination_sn=self.unit_serial_number,reason=f'1 unidad del lote instalada en {self.unit_serial_number}. Quedan {remaining}.',registered_by=user);record.save(update_fields=['status','updated_at'])
    else:
     record.status='assigned';record.current_sn=self.unit_serial_number;record.current_technician=user.get_username();data=dict(record.data or {})
     for field in record.table.inventory_fields.all():
      key=field.key.casefold();name=field.name.casefold()
      if field.is_destination_sn or key=='sn':data[field.key]=self.unit_serial_number
      if field.is_technician or 'tecnic' in key or 'tecnic' in name:data[field.key]=user.get_username()
      if field.field_type=='date' or 'fecha' in key or 'fecha' in name:data[field.key]=timezone.localdate().isoformat()
     record.data=data;record.save(update_fields=['status','current_sn','current_technician','data','updated_at']);RecordMovement.objects.create(record=record,movement_type='assign',technician_name=user.get_username(),destination_sn=self.unit_serial_number,reason=f'Componente instalado en unidad {self.unit_serial_number}.',registered_by=user)
   return repair
class RMA(models.Model):
 STATUS=[('open','Abierto'),('review','En evaluación'),('approved','Aprobado'),('rejected','Rechazado'),('closed','Cerrado')];ORIGINS=[('supplier','Proveedor'),('original','Original de la unidad'),('warehouse','Reserva de almacén')];component=models.ForeignKey(Component,on_delete=models.PROTECT,related_name='rmas',null=True,blank=True);component_type=models.ForeignKey(ComponentType,on_delete=models.PROTECT,related_name='rmas',null=True,blank=True);unit=models.ForeignKey(OrderUnit,on_delete=models.PROTECT,related_name='rmas',null=True,blank=True);reservation=models.ForeignKey(ComponentReservation,on_delete=models.PROTECT,related_name='rmas',null=True,blank=True);supplier=models.ForeignKey(Supplier,on_delete=models.PROTECT,related_name='rmas',null=True,blank=True);origin=models.CharField(max_length=16,choices=ORIGINS,default='supplier',db_index=True);reason=models.TextField(blank=True);status=models.CharField(max_length=12,choices=STATUS,default='open',db_index=True);created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='rmas_created');created_at=models.DateTimeField(auto_now_add=True);observations=models.TextField(blank=True)
class SavedQuery(models.Model):
 name=models.CharField(max_length=180,unique=True);description=models.TextField(blank=True);sql=models.TextField();active=models.BooleanField(default=True,db_index=True);is_system=models.BooleanField(default=False,db_index=True);original_sql=models.TextField(blank=True);created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='saved_queries_created');created_at=models.DateTimeField(auto_now_add=True);updated_at=models.DateTimeField(auto_now=True)
 def __str__(self):return self.name
class DevelopmentBatch(models.Model):
 STATUS=[('active','Activo'),('reverted','Revertido'),('purged','Eliminado por vaciado')];token=models.CharField(max_length=32,unique=True,db_index=True);source=models.CharField(max_length=255,blank=True);status=models.CharField(max_length=12,choices=STATUS,default='active',db_index=True);manifest=models.JSONField(default=dict,blank=True);created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='development_batches_created');created_at=models.DateTimeField(auto_now_add=True,db_index=True);reverted_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='development_batches_reverted');reverted_at=models.DateTimeField(null=True,blank=True)
 class Meta:ordering=('-created_at','-pk')
 def __str__(self):return self.token