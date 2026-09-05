from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404,redirect,render
from django.views.decorators.http import require_POST
from .models import InventoryTable,InventoryRecord,RecordMovement,AuditLog
from .order_models import OrderUnit,Component,ComponentReservation
from .component_flow_models import ReservationAllocation,ComponentCatalog

def _can_reserve(user):return user.is_authenticated and not getattr(getattr(user,'inventory_profile',None),'is_guest',False)
def _deny():return HttpResponseForbidden('No tienes permiso para realizar esta operación.')
def _is_catalog(record):
 try:record.table.component_catalog;return True
 except Exception:return False
def _quantity(record):
 try:return max(0,int((record.data or {}).get('quantity') or 0))
 except (TypeError,ValueError):return 0
def _available(record):return _quantity(record)>0 if _is_catalog(record) else record.status=='available'
def _record_reference(record):
 for key in ('referencia','reference','ref','modelo','model','descripcion','description'):
  value=(record.data or {}).get(key)
  if value:return str(value).strip()
 return record.internal_id
def _component_for_record(record):
 linked=Component.objects.filter(inventory_record=record).first()
 if linked:return linked
 return Component.objects.create(component_type=record.table.name,reference=_record_reference(record),inventory_record=record,status='active')
def _table_count(table):
 try:table.component_catalog;return sum(1 for r in table.records.all() if _quantity(r)>0)
 except Exception:return table.records.filter(status='available').count()
@login_required
def warehouse_table_menu(request,unit_pk):
 if not _can_reserve(request.user):return _deny()
 unit=get_object_or_404(OrderUnit.objects.select_related('order','order__customer'),pk=unit_pk)
 if unit.order.status!='open':messages.error(request,'El pedido está cerrado.');return redirect('unit_detail',pk=unit.pk)
 warehouse_tables=InventoryTable.objects.filter(active=True,component_catalog__isnull=True).order_by('position','name')
 tables=[{'table':table,'count':_table_count(table),'fields':table.inventory_fields.count()} for table in warehouse_tables]
 return render(request,'inventory/reservation_inventory_menu.html',{'unit':unit,'tables':tables,'reservation_origin':'warehouse'})
@login_required
def warehouse_inventory_table(request,unit_pk,slug):
 if not _can_reserve(request.user):return _deny()
 unit=get_object_or_404(OrderUnit.objects.select_related('order','order__customer'),pk=unit_pk);table=get_object_or_404(InventoryTable,slug=slug,active=True)
 if unit.order.status!='open':messages.error(request,'El pedido está cerrado.');return redirect('unit_detail',pk=unit.pk)
 fields=list(table.inventory_fields.all());q=(request.GET.get('q') or '').strip();records=list(table.records.all().order_by('internal_id'))
 try:table.component_catalog;records=[r for r in records if _quantity(r)>0]
 except Exception:records=[r for r in records if r.status=='available']
 if q:
  needle=q.casefold();records=[r for r in records if needle in ' '.join([r.internal_id]+[str(v) for v in (r.data or {}).values()]).casefold()]
 rows=[{'record':r,'values':[r.internal_id]+[(r.data or {}).get(f.key,'') for f in fields],'available_quantity':_quantity(r) if _is_catalog(r) else 1} for r in records[:1000]]
 return render(request,'inventory/reservation_inventory_table.html',{'unit':unit,'table':table,'fields':fields,'rows':rows,'q':q,'is_component_table':hasattr(table,'component_catalog')})
@login_required
def order_inventory_components(request,unit_pk):
 if not _can_reserve(request.user):return _deny()
 unit=get_object_or_404(OrderUnit.objects.select_related('order','order__customer'),pk=unit_pk)
 if unit.order.status!='open':messages.error(request,'El pedido está cerrado.');return redirect('unit_detail',pk=unit.pk)
 catalogs=ComponentCatalog.objects.select_related('component_type','inventory_table').filter(active=True,component_type__active=True,inventory_table__active=True).order_by('component_type__name')
 tables=[{'table':c.inventory_table,'count':_table_count(c.inventory_table),'fields':c.inventory_table.inventory_fields.count(),'component_type':c.component_type} for c in catalogs]
 return render(request,'inventory/reservation_inventory_menu.html',{'unit':unit,'tables':tables,'reservation_origin':'components'})
@login_required
@require_POST
def reserve_inventory_record(request,unit_pk,record_pk):
 if not _can_reserve(request.user):return _deny()
 with transaction.atomic():
  unit=get_object_or_404(OrderUnit.objects.select_for_update().select_related('order'),pk=unit_pk)
  if unit.order.status!='open':messages.error(request,'El pedido está cerrado.');return redirect('unit_detail',pk=unit.pk)
  record=get_object_or_404(InventoryRecord.objects.select_for_update().select_related('table'),pk=record_pk)
  if not _available(record):messages.error(request,'Este objeto ya no está disponible.');return redirect('warehouse_inventory_table',unit_pk=unit.pk,slug=record.table.slug)
  component=_component_for_record(record);catalog=_is_catalog(record)
  if not catalog and component.status!='active':messages.error(request,'Este componente ya está reservado o instalado.');return redirect('warehouse_inventory_table',unit_pk=unit.pk,slug=record.table.slug)
  requested=1
  if catalog:
   try:requested=max(1,int(request.POST.get('quantity') or 1))
   except (TypeError,ValueError):requested=1
   available=_quantity(record)
   if requested>available:
    messages.error(request,f'Sólo hay {available} unidad(es) disponibles.');return redirect('warehouse_inventory_table',unit_pk=unit.pk,slug=record.table.slug)
  # ComponentReservation representa una pieza física reservada. Para cantidades >1
  # se crean reservas unitarias, manteniendo instalación/confirmación individual.
  for _ in range(requested):
   reservation=ComponentReservation.objects.create(unit=unit,component=component,technician=request.user,unit_serial_number=unit.serial_number,observations='Reserva directa desde inventario/bodega')
   ReservationAllocation.objects.create(reservation=reservation,order=unit.order,source='order' if catalog else 'warehouse',authorization=None)
  if catalog:
   data=dict(record.data or {});remaining=_quantity(record)-requested;data['quantity']=str(remaining);record.data=data;record.status='available' if remaining>0 else 'reserved';component.status='active' if remaining>0 else 'low';component.save(update_fields=['status']);record.save(update_fields=['data','status','updated_at']);reason=f'{requested} unidad(es) reservadas para {unit.serial_number}. Quedan {remaining}.'
  else:
   component.status='reserved';component.save(update_fields=['status']);record.status='reserved';record.current_sn=unit.serial_number;record.current_technician=request.user.get_username();record.save(update_fields=['status','current_sn','current_technician','updated_at']);reason=f'Reservado para unidad {unit.serial_number}'
  RecordMovement.objects.create(record=record,movement_type='reserve',technician_name=request.user.get_username(),destination_sn=unit.serial_number,reason=reason,registered_by=request.user);AuditLog.objects.create(user=request.user,action='component_reserved_for_unit',object_type='InventoryRecord',object_id=str(record.pk),details={'unit_id':unit.pk,'serial_number':unit.serial_number,'order_id':unit.order_id,'table':record.table.name,'record_id':record.internal_id,'quantity_reserved':requested})
 messages.success(request,f'{record.internal_id}: {requested} unidad(es) reservada(s) para {unit.serial_number}.');return redirect('warehouse_inventory_table',unit_pk=unit.pk,slug=record.table.slug)
