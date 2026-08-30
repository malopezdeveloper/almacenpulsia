from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404,redirect,render
from django.views.decorators.http import require_POST
from .models import InventoryTable,InventoryRecord,RecordMovement,AuditLog
from .order_models import OrderUnit,Component,ComponentReservation
from .component_flow_models import ReservationAllocation
from .permissions import user_has_permission


def _can_reserve(user):
 return user.is_superuser or user.is_staff or user_has_permission(user,'components.reserve') or user_has_permission(user,'repairs.manage')

def _deny():return HttpResponseForbidden('No tienes permiso para realizar esta operación.')
def _available(record):return record.status=='available'

def _record_reference(record):
 for key in ('referencia','reference','ref','modelo','model','descripcion','description'):
  value=(record.data or {}).get(key)
  if value:return str(value).strip()
 return record.internal_id

def _component_for_record(record):
 # La pieza física del inventario es la fuente de verdad. Component se crea/enlaza
 # sólo para reutilizar el historial de ComponentReservation ya existente.
 linked=Component.objects.filter(inventory_record=record).first()
 if linked:return linked
 return Component.objects.create(component_type=record.table.name,reference=_record_reference(record),inventory_record=record,status='active')

@login_required
def warehouse_table_menu(request,unit_pk):
 if not _can_reserve(request.user):return _deny()
 unit=get_object_or_404(OrderUnit.objects.select_related('order','order__customer'),pk=unit_pk)
 if unit.order.status!='open':messages.error(request,'El pedido está cerrado.');return redirect('unit_detail',pk=unit.pk)
 tables=[]
 for table in InventoryTable.objects.filter(active=True).order_by('position','name'):
  count=table.records.filter(status='available').count()
  tables.append({'table':table,'count':count,'fields':table.inventory_fields.count()})
 return render(request,'inventory/reservation_inventory_menu.html',{'unit':unit,'tables':tables})

@login_required
def warehouse_inventory_table(request,unit_pk,slug):
 if not _can_reserve(request.user):return _deny()
 unit=get_object_or_404(OrderUnit.objects.select_related('order','order__customer'),pk=unit_pk);table=get_object_or_404(InventoryTable,slug=slug,active=True)
 if unit.order.status!='open':messages.error(request,'El pedido está cerrado.');return redirect('unit_detail',pk=unit.pk)
 fields=list(table.inventory_fields.all());q=(request.GET.get('q') or '').strip();records=table.records.filter(status='available').order_by('internal_id')
 if q:
  ids=[];needle=q.casefold()
  for record in records.iterator():
   text=' '.join([record.internal_id]+[str(v) for v in (record.data or {}).values()])
   if needle in text.casefold():ids.append(record.pk)
  records=table.records.filter(pk__in=ids,status='available').order_by('internal_id')
 rows=[{'record':r,'values':[r.internal_id]+[r.data.get(f.key,'') for f in fields]} for r in records[:1000]]
 return render(request,'inventory/reservation_inventory_table.html',{'unit':unit,'table':table,'fields':fields,'rows':rows,'q':q})

@login_required
def order_inventory_components(request,unit_pk):
 # "Componentes" lleva a la tabla funcional Componentes, no a cupos/autorizaciones.
 if not _can_reserve(request.user):return _deny()
 unit=get_object_or_404(OrderUnit.objects.select_related('order'),pk=unit_pk)
 table=InventoryTable.objects.filter(Q(name__iexact='Componentes')|Q(slug__iexact='componentes'),active=True).first()
 if table:return redirect('warehouse_inventory_table',unit_pk=unit.pk,slug=table.slug)
 messages.error(request,'No existe una tabla activa llamada Componentes.');return redirect('warehouse_table_menu',unit_pk=unit.pk)

@login_required
@require_POST
def reserve_inventory_record(request,unit_pk,record_pk):
 if not _can_reserve(request.user):return _deny()
 with transaction.atomic():
  unit=get_object_or_404(OrderUnit.objects.select_for_update().select_related('order'),pk=unit_pk)
  if unit.order.status!='open':messages.error(request,'El pedido está cerrado.');return redirect('unit_detail',pk=unit.pk)
  record=get_object_or_404(InventoryRecord.objects.select_for_update().select_related('table'),pk=record_pk)
  if not _available(record):messages.error(request,'Este objeto ya no está disponible.');return redirect('warehouse_inventory_table',unit_pk=unit.pk,slug=record.table.slug)
  component=_component_for_record(record)
  if component.status!='active':messages.error(request,'Este componente ya está reservado o instalado.');return redirect('warehouse_inventory_table',unit_pk=unit.pk,slug=record.table.slug)
  reservation=ComponentReservation.objects.create(unit=unit,component=component,technician=request.user,unit_serial_number=unit.serial_number,observations='Reserva directa desde inventario/bodega')
  ReservationAllocation.objects.create(reservation=reservation,order=unit.order,source='warehouse',authorization=None)
  component.status='reserved';component.save(update_fields=['status']);record.status='reserved';record.current_sn=unit.serial_number;record.current_technician=request.user.get_username();record.save(update_fields=['status','current_sn','current_technician','updated_at'])
  RecordMovement.objects.create(record=record,movement_type='reserve',technician_name=request.user.get_username(),destination_sn=unit.serial_number,reason=f'Reservado para unidad {unit.serial_number}',registered_by=request.user)
  AuditLog.objects.create(user=request.user,action='component_reserved_for_unit',object_type='InventoryRecord',object_id=str(record.pk),details={'unit_id':unit.pk,'serial_number':unit.serial_number,'order_id':unit.order_id,'table':record.table.name,'record_id':record.internal_id})
 messages.success(request,f'{record.internal_id} reservado para {unit.serial_number}. La reserva queda registrada en el expediente de la unidad.')
 return redirect('warehouse_inventory_table',unit_pk=unit.pk,slug=record.table.slug)
