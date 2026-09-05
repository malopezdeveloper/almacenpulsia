from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from .order_models import Component,ComponentReservation,ComponentType,OrderUnit
from .component_flow_models import OrderComponentAuthorization,ComponentIncreaseRequest,ReservationAllocation
from .permissions import user_has_permission

def _can_reserve(user):return user.is_authenticated and not getattr(getattr(user,'inventory_profile',None),'is_guest',False)
def _can_approve(user):return user.is_superuser or user_has_permission(user,'components.manage') or user_has_permission(user,'orders.manage')
def _deny():return HttpResponseForbidden('No tienes permiso para realizar esta operación.')
def _is_stock_order(order):return order.name.strip().casefold()=='stock'
def _authorization_usage(auth):return auth.allocations.filter(reservation__status__in=['active','installed','confirmed']).count()
def _require_open(unit):return unit.order.status=='open'

@login_required
def reservation_source(request,unit_pk):
 if not _can_reserve(request.user):return _deny()
 unit=get_object_or_404(OrderUnit.objects.select_related('order','order__customer'),pk=unit_pk)
 if not _require_open(unit):messages.error(request,'El pedido está cerrado. Reábrelo antes de reservar componentes.');return redirect('unit_detail',pk=unit.pk)
 return render(request,'inventory/reservation_source.html',{'unit':unit})
@login_required
def warehouse_components(request,unit_pk):
 if not _can_reserve(request.user):return _deny()
 unit=get_object_or_404(OrderUnit.objects.select_related('order'),pk=unit_pk)
 if not _require_open(unit):return redirect('unit_detail',pk=unit.pk)
 return redirect('warehouse_table_menu',unit_pk=unit.pk)
@login_required
def order_components(request,unit_pk):
 if not _can_reserve(request.user):return _deny()
 unit=get_object_or_404(OrderUnit.objects.select_related('order'),pk=unit_pk)
 if not _require_open(unit):return redirect('unit_detail',pk=unit.pk)
 return redirect('order_inventory_components',unit_pk=unit.pk)
@login_required
def authorized_physical_components(request,unit_pk,auth_pk):return redirect('order_inventory_components',unit_pk=unit_pk)
@login_required
@require_POST
def reserve_physical_component(request,unit_pk,component_pk,source):
 if not _can_reserve(request.user):return _deny()
 messages.info(request,'La reserva física se realiza ahora directamente desde las tablas de inventario.')
 return redirect('warehouse_table_menu' if source=='warehouse' else 'order_inventory_components',unit_pk=unit_pk)
@login_required
@require_POST
def legacy_reserve_component(request,component_pk):
 if not _can_reserve(request.user):return _deny()
 unit_id=request.POST.get('unit')
 if not unit_id:messages.error(request,'Selecciona primero una unidad.');return redirect('internal_detail',kind='componentes',pk=component_pk)
 with transaction.atomic():
  unit=get_object_or_404(OrderUnit.objects.select_for_update().select_related('order'),pk=unit_id);component=get_object_or_404(Component.objects.select_for_update(),pk=component_pk)
  if not _require_open(unit):messages.error(request,'El pedido está cerrado.');return redirect('internal_detail',kind='componentes',pk=component.pk)
  if component.status!='active':messages.error(request,'Este componente ya no está disponible.');return redirect('internal_detail',kind='componentes',pk=component.pk)
  reservation=ComponentReservation.objects.create(unit=unit,component=component,technician=request.user,unit_serial_number=unit.serial_number,observations='Reserva directa desde Componentes');ReservationAllocation.objects.create(reservation=reservation,order=unit.order,source='order',authorization=None);component.status='reserved';component.save(update_fields=['status'])
 messages.success(request,f'{component} reservado para {unit.serial_number}.');return redirect('unit_detail',pk=unit.pk)
@login_required
@require_POST
def request_component_increase(request,unit_pk):
 if not _can_reserve(request.user):return _deny()
 unit=get_object_or_404(OrderUnit.objects.select_related('order'),pk=unit_pk);kind=get_object_or_404(ComponentType,pk=request.POST.get('component_type'),active=True)
 try:qty=max(int(request.POST.get('quantity') or 1),1)
 except ValueError:qty=1
 if ComponentIncreaseRequest.objects.filter(order=unit.order,unit=unit,component_type=kind,status='pending').exists():messages.info(request,'Ya existe una solicitud pendiente.');return redirect('order_inventory_components',unit_pk=unit.pk)
 ComponentIncreaseRequest.objects.create(order=unit.order,unit=unit,component_type=kind,requested_quantity=qty,requested_by=request.user,observations=(request.POST.get('observations') or '').strip());messages.success(request,'Solicitud creada.');return redirect('order_inventory_components',unit_pk=unit.pk)
@login_required
@require_POST
def resolve_component_increase(request,request_pk,action):
 if not _can_approve(request.user) or action not in ('approve','reject'):return _deny()
 with transaction.atomic():
  req=get_object_or_404(ComponentIncreaseRequest.objects.select_for_update().select_related('order','component_type'),pk=request_pk,status='pending');req.status='approved' if action=='approve' else 'rejected';req.resolved_by=request.user;req.resolved_at=timezone.now();req.save(update_fields=['status','resolved_by','resolved_at'])
 return redirect('order_inventory_components',unit_pk=req.unit_id)
