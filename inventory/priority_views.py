from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction, models
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import AuditLog, ProductionZone
from .order_models import CustomerOrder, OrderUnit
from .priority_models import BoardPriority
from .unit_workflow_models import PhysicalUnitLocation
from .permissions import user_has_permission


def _can_manage(user): return user.is_superuser or user.is_staff or user_has_permission(user,'orders.manage')
def stock_order(): return CustomerOrder.objects.filter(name__iexact='stock',customer__isnull=True).order_by('pk').first()
def _new_cycle(source,destination):
 return OrderUnit.objects.create(order=destination,physical_unit=source.physical_unit,serial_number=source.serial_number,aiken_lot=source.aiken_lot,aiken_unit_id=source.aiken_unit_id,brand=source.brand,model=source.model,processor=source.processor,ram=source.ram,disk=source.disk)
def _in_production(unit): return PhysicalUnitLocation.objects.filter(physical_unit=unit.physical_unit).exists()

@login_required
def priority_check(request):
 zone_id=(request.GET.get('zone') or '').strip();context=(request.GET.get('work_order') or 'stock').strip();sn=(request.GET.get('sn') or '').strip();applicable=BoardPriority.objects.filter(active=True).filter(models.Q(zone__isnull=True)|models.Q(zone_id=zone_id)).select_related('order','zone')
 if not applicable.exists():return JsonResponse({'has_priority':False,'is_priority':True})
 order=None
 if context!='stock':
  try:order=CustomerOrder.objects.filter(pk=int(context)).first()
  except (TypeError,ValueError):pass
 if order is None and sn:
  unit=OrderUnit.objects.filter(serial_number__iexact=sn).select_related('order').order_by('-imported_at','-pk').first();order=unit.order if unit else None
 priority_orders=list(applicable.values_list('order_id','order__name'));is_priority=bool(order and any(pk==order.pk for pk,_ in priority_orders));names=', '.join(dict.fromkeys(name for _,name in priority_orders));return JsonResponse({'has_priority':True,'is_priority':is_priority,'order':order.name if order else '','priority_orders':names,'message':f'ATENCIÓN: esta unidad no es prioridad en esta zona. Prioridad actual: {names}. Puedes procesarla igualmente.' if not is_priority else ''})
@login_required
def priority_panel(request):
 if not _can_manage(request.user):return HttpResponseForbidden('Sólo Gestor y Administradores pueden gestionar prioridades.')
 if request.method=='POST':
  order=get_object_or_404(CustomerOrder,pk=request.POST.get('order'),status='open')
  if order.name.casefold()=='stock':messages.error(request,'STOCK no puede establecerse como pedido prioritario.');return redirect('board_priorities')
  zone_id=(request.POST.get('zone') or '').strip();zone=get_object_or_404(ProductionZone,pk=zone_id,is_active=True) if zone_id else None;priority,created=BoardPriority.objects.get_or_create(order=order,zone=zone,defaults={'created_by':request.user,'active':True})
  if not created and not priority.active:priority.active=True;priority.created_by=request.user;priority.save(update_fields=['active','created_by'])
  AuditLog.objects.create(user=request.user,action='board_priority_enabled',object_type='CustomerOrder',object_id=str(order.pk),details={'order':order.name,'zone':zone.name if zone else 'ALL'});messages.success(request,f'Prioridad activada: {order.name} · {zone.name if zone else "Todas las zonas"}.');return redirect('board_priorities')
 priorities=BoardPriority.objects.filter(active=True).select_related('order','zone','created_by');orders=CustomerOrder.objects.filter(status='open').exclude(name__iexact='stock').select_related('customer').order_by('-pk');zones=ProductionZone.objects.filter(is_active=True).order_by('position','name');return render(request,'inventory/board_priorities.html',{'priorities':priorities,'orders':orders,'zones':zones})
@login_required
@require_POST
def priority_disable(request,pk):
 if not _can_manage(request.user):return HttpResponseForbidden('Sólo Gestor y Administradores pueden gestionar prioridades.')
 priority=get_object_or_404(BoardPriority.objects.select_related('order','zone'),pk=pk);priority.active=False;priority.save(update_fields=['active']);AuditLog.objects.create(user=request.user,action='board_priority_disabled',object_type='CustomerOrder',object_id=str(priority.order_id),details={'order':priority.order.name,'zone':priority.zone.name if priority.zone_id else 'ALL'});messages.success(request,'Prioridad retirada.');return redirect('board_priorities')
@login_required
@require_POST
def move_unit_to_stock(request,unit_pk):
 if not _can_manage(request.user):return HttpResponseForbidden('Sólo Gestor y Administradores pueden sacar unidades de un pedido.')
 unit=get_object_or_404(OrderUnit.objects.select_related('order','physical_unit'),pk=unit_pk);stock=stock_order()
 if stock is None:messages.error(request,'No existe el pedido permanente STOCK. Ejecuta las migraciones de la actualización.');return redirect('order_detail',pk=unit.order_id)
 current=OrderUnit.objects.filter(physical_unit=unit.physical_unit).order_by('-imported_at','-pk').first()
 if current and current.pk!=unit.pk:messages.error(request,'Ese ciclo ya no es el actual del equipo. Abre el ciclo más reciente.');return redirect('order_detail',pk=unit.order_id)
 if unit.order_id==stock.pk:messages.info(request,f'{unit.serial_number} ya pertenece a STOCK.');return redirect('order_detail',pk=stock.pk)
 if _in_production(unit):messages.error(request,'La unidad está activa en Pizarra. Finaliza primero la intervención antes de cambiar su ciclo.');return redirect('order_detail',pk=unit.order_id)
 source_id=unit.order_id;source_name=unit.order.name
 with transaction.atomic():
  new_unit=_new_cycle(unit,stock);AuditLog.objects.create(user=request.user,action='order_unit_new_stock_cycle',object_type='OrderUnit',object_id=str(new_unit.pk),details={'serial_number':unit.serial_number,'previous_cycle_id':unit.pk,'from_order_id':source_id,'from_order':source_name,'to_order_id':stock.pk,'to_order':'STOCK','reason':'returned_for_reconditioning'})
 messages.success(request,f'{unit.serial_number} recibida de vuelta: creado nuevo ciclo en STOCK sin alterar su historial anterior.');return redirect('order_detail',pk=stock.pk)
@login_required
@require_POST
def move_unit_from_stock(request,unit_pk):
 if not _can_manage(request.user):return HttpResponseForbidden('Sólo Gestor y Administradores pueden asignar unidades de STOCK a pedidos.')
 stock=stock_order()
 if stock is None:messages.error(request,'No existe el pedido permanente STOCK.');return redirect('internal_table',kind='pedidos')
 unit=get_object_or_404(OrderUnit.objects.select_related('order','physical_unit'),pk=unit_pk,order=stock);destination=get_object_or_404(CustomerOrder,pk=request.POST.get('order_id'),status='open')
 current=OrderUnit.objects.filter(physical_unit=unit.physical_unit).order_by('-imported_at','-pk').first()
 if current and current.pk!=unit.pk:messages.error(request,'Ese ciclo de STOCK ya no es el actual del equipo.');return redirect('order_detail',pk=stock.pk)
 if destination.pk==stock.pk or destination.name.casefold()=='stock':messages.error(request,'Selecciona un pedido de destino distinto de STOCK.');return redirect('order_detail',pk=stock.pk)
 if _in_production(unit):messages.error(request,'La unidad está activa en Pizarra. Finaliza primero la intervención antes de asignarla a un pedido.');return redirect('order_detail',pk=stock.pk)
 with transaction.atomic():
  new_unit=_new_cycle(unit,destination);AuditLog.objects.create(user=request.user,action='stock_unit_new_order_cycle',object_type='OrderUnit',object_id=str(new_unit.pk),details={'serial_number':unit.serial_number,'previous_cycle_id':unit.pk,'from_order_id':stock.pk,'from_order':'STOCK','to_order_id':destination.pk,'to_order':destination.name})
 messages.success(request,f'{unit.serial_number} asignada a {destination.name} en un nuevo ciclo; el ciclo de STOCK queda conservado como histórico.');return redirect('order_detail',pk=destination.pk)
