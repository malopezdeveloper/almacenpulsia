from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from .order_models import Component,ComponentReservation,ComponentType,OrderUnit
from .component_flow_models import OrderComponentAuthorization,ComponentIncreaseRequest,ReservationAllocation
from .permissions import user_has_permission

def _can_reserve(user):return user.is_superuser or user_has_permission(user,'components.reserve') or user_has_permission(user,'repairs.manage') or user.is_staff
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
 unit=get_object_or_404(OrderUnit.objects.select_related('order','order__customer'),pk=unit_pk)
 if not _require_open(unit):return redirect('unit_detail',pk=unit.pk)
 qs=Component.objects.filter(status='active').select_related('component_kind','supplier').order_by('component_type','reference','pk');q=(request.GET.get('q') or '').strip()
 if q:qs=qs.filter(Q(component_type__icontains=q)|Q(reference__icontains=q)|Q(supplier__name__icontains=q))
 return render(request,'inventory/reservation_warehouse.html',{'unit':unit,'page':Paginator(qs,50).get_page(request.GET.get('page')),'q':q})
@login_required
def order_components(request,unit_pk):
 if not _can_reserve(request.user):return _deny()
 unit=get_object_or_404(OrderUnit.objects.select_related('order','order__customer'),pk=unit_pk)
 if not _require_open(unit):return redirect('unit_detail',pk=unit.pk)
 order=unit.order;authorizations=list(OrderComponentAuthorization.objects.filter(order=order).select_related('component_type').order_by('component_type__name'));rows=[]
 for auth in authorizations:
  used=_authorization_usage(auth);remaining=None if (auth.unlimited or _is_stock_order(order)) else max(auth.approved_quantity-used,0);available=Component.objects.filter(status='active',component_kind=auth.component_type).count();rows.append({'auth':auth,'used':used,'remaining':remaining,'available_physical':available})
 return render(request,'inventory/reservation_order_components.html',{'unit':unit,'rows':rows,'component_types':ComponentType.objects.filter(active=True).order_by('name'),'requests':unit.component_increase_requests.select_related('component_type','requested_by','resolved_by').all(),'is_stock_order':_is_stock_order(order),'can_approve':_can_approve(request.user)})
@login_required
def authorized_physical_components(request,unit_pk,auth_pk):
 if not _can_reserve(request.user):return _deny()
 unit=get_object_or_404(OrderUnit.objects.select_related('order'),pk=unit_pk);auth=get_object_or_404(OrderComponentAuthorization.objects.select_related('component_type'),pk=auth_pk,order=unit.order)
 if not _require_open(unit):return redirect('unit_detail',pk=unit.pk)
 used=_authorization_usage(auth)
 if not (_is_stock_order(unit.order) or auth.unlimited) and used>=auth.approved_quantity:messages.warning(request,'El cupo autorizado está agotado. Debe solicitar una ampliación.');return redirect('order_components',unit_pk=unit.pk)
 qs=Component.objects.filter(status='active',component_kind=auth.component_type).select_related('supplier').order_by('reference','pk');q=(request.GET.get('q') or '').strip()
 if q:qs=qs.filter(Q(reference__icontains=q)|Q(supplier__name__icontains=q))
 return render(request,'inventory/reservation_authorized_components.html',{'unit':unit,'auth':auth,'page':Paginator(qs,50).get_page(request.GET.get('page')),'q':q})
@login_required
@require_POST
def reserve_physical_component(request,unit_pk,component_pk,source):
 if not _can_reserve(request.user) or source not in ('warehouse','order'):return _deny()
 with transaction.atomic():
  unit=get_object_or_404(OrderUnit.objects.select_related('order'),pk=unit_pk)
  if not _require_open(unit):messages.error(request,'El pedido está cerrado.');return redirect('unit_detail',pk=unit.pk)
  component=get_object_or_404(Component.objects.select_for_update().select_related('component_kind'),pk=component_pk,status='active');authorization=None
  if source=='order':
   if component.component_kind_id is None:messages.error(request,'Este componente no tiene un tipo normalizado. Puede reservarse desde Bodega.');return redirect('order_components',unit_pk=unit.pk)
   authorization=OrderComponentAuthorization.objects.select_for_update().filter(order=unit.order,component_type=component.component_kind).first()
   if authorization is None:
    if _is_stock_order(unit.order):authorization=OrderComponentAuthorization.objects.create(order=unit.order,component_type=component.component_kind,unlimited=True,updated_by=request.user)
    else:messages.error(request,'Este tipo no tiene cupo autorizado para el Pedido.');return redirect('order_components',unit_pk=unit.pk)
   used=_authorization_usage(authorization)
   if not (_is_stock_order(unit.order) or authorization.unlimited) and used>=authorization.approved_quantity:messages.error(request,'El cupo autorizado se agotó antes de completar la reserva.');return redirect('order_components',unit_pk=unit.pk)
  reservation=ComponentReservation.objects.create(unit=unit,component=component,technician=request.user,unit_serial_number=unit.serial_number,observations=(request.POST.get('observations') or '').strip());ReservationAllocation.objects.create(reservation=reservation,order=unit.order,source=source,authorization=authorization);component.status='reserved';component.save(update_fields=['status'])
 messages.success(request,f'Componente reservado desde {"Bodega" if source=="warehouse" else "Componentes del pedido"}.');return redirect('unit_detail',pk=unit.pk)
@login_required
@require_POST
def legacy_reserve_component(request,component_pk):
 if not _can_reserve(request.user):return _deny()
 unit_id=request.POST.get('unit')
 if not unit_id:messages.error(request,'Selecciona primero una unidad.');return redirect('internal_table',kind='componentes')
 return redirect('reservation_source',unit_pk=get_object_or_404(OrderUnit,pk=unit_id).pk)
@login_required
@require_POST
def request_component_increase(request,unit_pk):
 if not _can_reserve(request.user):return _deny()
 unit=get_object_or_404(OrderUnit.objects.select_related('order'),pk=unit_pk)
 if not _require_open(unit):messages.error(request,'El pedido está cerrado.');return redirect('unit_detail',pk=unit.pk)
 kind=get_object_or_404(ComponentType,pk=request.POST.get('component_type'),active=True)
 try:qty=max(int(request.POST.get('quantity') or 1),1)
 except ValueError:qty=1
 if _is_stock_order(unit.order):messages.info(request,'STOCK no tiene límite administrativo. Reserva una pieza física desde Bodega.');return redirect('warehouse_components',unit_pk=unit.pk)
 if ComponentIncreaseRequest.objects.filter(order=unit.order,unit=unit,component_type=kind,status='pending').exists():messages.info(request,'Ya existe una solicitud pendiente para este tipo y unidad.');return redirect('order_components',unit_pk=unit.pk)
 ComponentIncreaseRequest.objects.create(order=unit.order,unit=unit,component_type=kind,requested_quantity=qty,requested_by=request.user,observations=(request.POST.get('observations') or '').strip());messages.success(request,'Solicitud creada como alerta pendiente. No existe reserva física hasta registrar y seleccionar una pieza real.');return redirect('order_components',unit_pk=unit.pk)
@login_required
@require_POST
def resolve_component_increase(request,request_pk,action):
 if not _can_approve(request.user) or action not in ('approve','reject'):return _deny()
 with transaction.atomic():
  req=get_object_or_404(ComponentIncreaseRequest.objects.select_for_update().select_related('order','component_type'),pk=request_pk,status='pending')
  if action=='approve':
   auth,_=OrderComponentAuthorization.objects.select_for_update().get_or_create(order=req.order,component_type=req.component_type);auth.unlimited=auth.unlimited or _is_stock_order(req.order)
   if not auth.unlimited:auth.approved_quantity+=req.requested_quantity
   auth.updated_by=request.user;auth.save();req.status='approved';messages.success(request,'Ampliación autorizada. Aún no existe reserva física.')
  else:req.status='rejected';messages.success(request,'Solicitud rechazada.')
  req.resolved_by=request.user;req.resolved_at=timezone.now();req.save(update_fields=['status','resolved_by','resolved_at'])
 return redirect('order_components',unit_pk=req.unit_id)
