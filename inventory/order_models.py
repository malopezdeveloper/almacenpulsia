from django.conf import settings
from django.db import models, transaction
from django.utils import timezone


class BusinessRole(models.Model):
    name=models.CharField(max_length=80,unique=True)
    code=models.SlugField(max_length=80,unique=True)
    permissions=models.JSONField(default=list,blank=True)
    active=models.BooleanField(default=True)
    protected=models.BooleanField(default=False)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    def __str__(self): return self.name

class BusinessRoleAssignment(models.Model):
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name='pulsia_role_assignments')
    role=models.ForeignKey(BusinessRole,on_delete=models.PROTECT,related_name='assignments')
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta: constraints=[models.UniqueConstraint(fields=['user','role'],name='unique_pulsia_user_role')]

class Customer(models.Model):
    name=models.CharField(max_length=180,unique=True,db_index=True)
    phone=models.CharField(max_length=80,blank=True)
    email=models.EmailField(blank=True)
    address=models.CharField(max_length=300,blank=True)
    delivery_point=models.CharField(max_length=300,blank=True)
    contact=models.CharField(max_length=180,blank=True)
    observations=models.TextField(blank=True)
    active=models.BooleanField(default=True)
    def __str__(self): return self.name

class Supplier(models.Model):
    name=models.CharField(max_length=180,unique=True,db_index=True)
    phone=models.CharField(max_length=80,blank=True)
    email=models.EmailField(blank=True)
    address=models.CharField(max_length=300,blank=True)
    delivery_point=models.CharField(max_length=300,blank=True)
    contact=models.CharField(max_length=180,blank=True)
    observations=models.TextField(blank=True)
    active=models.BooleanField(default=True)
    def __str__(self): return self.name

class CustomerOrder(models.Model):
    name=models.CharField(max_length=180,db_index=True)
    customer=models.ForeignKey(Customer,on_delete=models.PROTECT,related_name='orders')
    brand=models.CharField(max_length=160,blank=True)
    model=models.CharField(max_length=180,blank=True)
    lot=models.CharField(max_length=160,blank=True,db_index=True)
    processor=models.CharField(max_length=180,blank=True)
    ram=models.CharField(max_length=80,blank=True)
    disk=models.CharField(max_length=80,blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='customer_orders_created')
    created_at=models.DateTimeField(auto_now_add=True)
    def __str__(self): return f'{self.pk} · {self.name}'

class OrderUnit(models.Model):
    order=models.ForeignKey(CustomerOrder,on_delete=models.CASCADE,related_name='units')
    serial_number=models.CharField(max_length=180,unique=True,db_index=True)
    aiken_lot=models.CharField(max_length=160,blank=True,db_index=True)
    brand=models.CharField(max_length=160,blank=True)
    model=models.CharField(max_length=180,blank=True)
    processor=models.CharField(max_length=180,blank=True)
    ram=models.CharField(max_length=80,blank=True)
    disk=models.CharField(max_length=80,blank=True)
    imported_at=models.DateTimeField(auto_now_add=True)
    def __str__(self): return self.serial_number

class Component(models.Model):
    STATUS=[('active','Activo'),('reserved','Reservado'),('low','Baja')]
    component_type=models.CharField(max_length=160,db_index=True)
    supplier=models.ForeignKey(Supplier,on_delete=models.PROTECT,related_name='components',null=True,blank=True)
    reference=models.CharField(max_length=200,blank=True,db_index=True)
    inventory_record=models.OneToOneField('inventory.InventoryRecord',on_delete=models.PROTECT,null=True,blank=True,related_name='managed_component')
    date=models.DateField(default=timezone.localdate)
    observations=models.TextField(blank=True)
    status=models.CharField(max_length=12,choices=STATUS,default='active',db_index=True)
    def __str__(self): return self.reference or f'{self.component_type} #{self.pk}'

class Repair(models.Model):
    unit=models.ForeignKey(OrderUnit,on_delete=models.PROTECT,related_name='repairs')
    repair_type=models.CharField(max_length=160,db_index=True)
    observations=models.TextField(blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='repairs_created')
    created_at=models.DateTimeField(auto_now_add=True)
    def __str__(self): return f'{self.unit.serial_number} · {self.repair_type}'

class ProcurementAlert(models.Model):
    STATUS=[('open','Abierta'),('resolved','Resuelta')]
    repair=models.ForeignKey(Repair,on_delete=models.CASCADE,related_name='procurement_alerts')
    message=models.CharField(max_length=500)
    status=models.CharField(max_length=12,choices=STATUS,default='open',db_index=True)
    created_at=models.DateTimeField(auto_now_add=True,db_index=True)
    resolved_at=models.DateTimeField(null=True,blank=True)

class ComponentReservation(models.Model):
    STATUS=[('active','Activa'),('delivered','Entregada'),('cancelled','Cancelada')]
    repair=models.ForeignKey(Repair,on_delete=models.PROTECT,related_name='component_reservations')
    component=models.ForeignKey(Component,on_delete=models.PROTECT,related_name='reservations')
    technician=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='component_reservations')
    unit_serial_number=models.CharField(max_length=180,db_index=True)
    status=models.CharField(max_length=12,choices=STATUS,default='active',db_index=True)
    reserved_at=models.DateTimeField(auto_now_add=True)
    resolved_at=models.DateTimeField(null=True,blank=True)
    observations=models.TextField(blank=True)
    class Meta: constraints=[models.UniqueConstraint(fields=['component'],condition=models.Q(status='active'),name='one_active_component_reservation')]
    def cancel(self):
        with transaction.atomic():
            self.status='cancelled'; self.resolved_at=timezone.now(); self.save(update_fields=['status','resolved_at'])
            self.component.status='active'; self.component.save(update_fields=['status'])
            if self.component.inventory_record_id:
                record=self.component.inventory_record
                record.status='available'; record.current_sn=''; record.current_technician=''; record.save(update_fields=['status','current_sn','current_technician','updated_at'])

class RMA(models.Model):
    STATUS=[('open','Abierto'),('review','En evaluación'),('approved','Aprobado'),('rejected','Rechazado'),('closed','Cerrado')]
    component=models.ForeignKey(Component,on_delete=models.PROTECT,related_name='rmas')
    supplier=models.ForeignKey(Supplier,on_delete=models.PROTECT,related_name='rmas')
    reason=models.TextField(blank=True)
    status=models.CharField(max_length=12,choices=STATUS,default='open',db_index=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='rmas_created')
    created_at=models.DateTimeField(auto_now_add=True)
    observations=models.TextField(blank=True)
    def clean(self):
        from django.core.exceptions import ValidationError
        if self.component_id and self.component.status!='low': raise ValidationError('Solo se puede abrir un RMA sobre un componente dado de baja.')
        if self.component_id and self.component.supplier_id and self.supplier_id!=self.component.supplier_id: raise ValidationError('El RMA debe dirigirse al proveedor del componente.')
