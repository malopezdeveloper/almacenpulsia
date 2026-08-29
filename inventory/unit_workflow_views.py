from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import ProductionModelMySQLSource, ProductionZone
from .order_models import CustomerOrder, OrderUnit, PhysicalUnit, ComponentType, ProcurementAlert, ComponentReservation
from .external_mysql import find_aiken_unit_exact
from .unit_workflow_models import UnitIntervention, UnitAlertOrigin, ReservationInstallation, RepairConfirmation
from .permissions import user_has_permission

def _can_work(user):return user.is_authenticated and not getattr(getattr(user,'inventory_profile',None),'is_guest',False)
def _can_confirm(user):return user.is_superuser or user_has_permission(user,'repairs.manage') or user_has_permission(user,'components.reserve') or user.is_staff
def _deny():return HttpResponseForbidden('No tienes permiso para esta operación.')
def _snapshot(unit):return {'serial_number':unit.serial_number,'order_id':unit.order_id,'order':unit.order.name,'brand':unit.brand,'model':unit.model,'processor':unit.processor,'ram':unit.ram,'disk':unit.disk,'aiken_lot':unit.aiken_lot,'aiken_unit_id':unit.aiken_unit_id}
def _local_cycle(sn):return OrderUnit.objects.select_related('order','order__customer','physical_unit').filter(serial_number__iexact=sn).order_by('-imported_at','-pk').first()
def _value(request,name,fallback=''):return (request.POST.get(name) if name in request.POST else fallback) or ''

@login_required
def serial_lookup(request):
 if not _can_work(request.user):return _deny()
 sn=(request.GET.get('sn') or '').strip()
 if not sn:return JsonResponse({'status':'empty'})
 local=_local_cycle(sn)
 if local:return JsonResponse({'status':'found','source':'local','unit_id':local.pk,'order_id':local.order_id,'order':local.order.name,'serial_number':local.serial_number,'brand':local.brand,'model':local.model,'processor':local.processor,'ram':local.ram,'disk':local.disk})
 source=ProductionModelMySQLSource.objects.order_by('-updated_at').first()
 if source:
  try:
   row=find_aiken_unit_exact(source,sn)
   if row:return JsonResponse({'status':'found','source':'aiken','serial_number':str(row.get('serial_number') or sn),'aiken':row})
  except Exception as exc:return JsonResponse({'status':'aiken_error','serial_number':sn,'message':str(exc),'manual_confirmation_required':True})
 return JsonResponse({'status':'not_found','serial_number':sn,'manual_confirmation_required':True})

@login_required
@require_POST
def start_unit_intervention(request):
 if not _can_work(request.user):return _deny()
 sn=(request.POST.get('serial_number') or '').strip();zone=get_object_or_404(ProductionZone,pk=request.POST.get('zone'),is_active=True)
 if not sn:messages.error(request,'Introduce un número de serie.');return redirect('production_board')
 unit=_local_cycle(sn);source_name='local';extra={}
 if not unit:
  source=ProductionModelMySQLSource.objects.order_by('-updated_at').first();row=None
  if source:
   try:row=find_aiken_unit_exact(source,sn)
   except Exception as exc:
    if request.POST.get('confirm_manual')!='yes':messages.error(request,f'AIKEN no pudo comprobar el SN: {exc}. Confirma expresamente el alta manual si procede.');return redirect('production_board')
  if row:
   if not request.POST.get('order'):return render(request,'inventory/unit_intervention_confirm.html',{'serial_number':sn,'zone':zone,'source':'aiken','aiken':row,'orders':CustomerOrder.objects.filter(status='open').order_by('-id')})
   order=get_object_or_404(CustomerOrder,pk=request.POST.get('order'),status='open')
   original={k:str(row.get(k) or '') for k in ('brand','model','processor','ram','disk','lot','id')};values={k:_value(request,k,original[k]).strip() for k in ('brand','model','processor','ram','disk')};lot=_value(request,'aiken_lot',original['lot'] or order.lot).strip()
   physical,_=PhysicalUnit.objects.get_or_create(serial_number=sn,defaults=values);unit,_=OrderUnit.objects.get_or_create(order=order,physical_unit=physical,defaults={'serial_number':sn,'aiken_lot':lot,'aiken_unit_id':original['id'],**values});source_name='aiken';extra={'aiken_original':original,'worker_values':dict(values,lot=lot),'worker_corrected':any(original[k].strip()!=values[k] for k in ('brand','model','processor','ram','disk')) or original['lot'].strip()!=lot}
  else:
   if request.POST.get('confirm_manual')!='yes':return render(request,'inventory/unit_intervention_confirm.html',{'serial_number':sn,'zone':zone,'source':'manual','orders':CustomerOrder.objects.filter(status='open').order_by('-id')})
   order=get_object_or_404(CustomerOrder,pk=request.POST.get('order'),status='open');values={k:_value(request,k).strip() for k in ('brand','model','processor','ram','disk')};lot=_value(request,'aiken_lot').strip();physical,_=PhysicalUnit.objects.get_or_create(serial_number=sn,defaults=values);unit,_=OrderUnit.objects.get_or_create(order=order,physical_unit=physical,defaults={'serial_number':sn,'aiken_lot':lot,**values});source_name='manual';extra={'worker_values':dict(values,lot=lot),'manual_confirmation':True}
 snap=_snapshot(unit);snap.update(extra);intervention=UnitIntervention.objects.create(unit=unit,worker=request.user,zone=zone,source=source_name,source_snapshot=snap);messages.success(request,f'{unit.serial_number} abierta en {zone.name}. Pedido: {unit.order.name}.');return redirect('unit_workbench',intervention_pk=intervention.pk)

@login_required
def unit_workbench(request,intervention_pk):
 intervention=get_object_or_404(UnitIntervention.objects.select_related('unit','unit__order','unit__order__customer','worker','zone'),pk=intervention_pk)
 if not _can_work(request.user):return _deny()
 unit=intervention.unit
 return render(request,'inventory/unit_workbench.html',{'intervention':intervention,'unit':unit,'alerts':unit.procurement_alerts.select_related('component_type').order_by('-created_at'),'reservations':unit.component_reservations.select_related('component','technician','installed_by','repair').order_by('-reserved_at'),'component_types':ComponentType.objects.filter(active=True).order_by('name'),'can_confirm':_can_confirm(request.user)})
@login_required
@require_POST
def create_unit_alert(request,intervention_pk):
 if not _can_work(request.user):return _deny()
 intervention=get_object_or_404(UnitIntervention.objects.select_related('unit','zone'),pk=intervention_pk);kind=get_object_or_404(ComponentType,pk=request.POST.get('component_type'),active=True)
 with transaction.atomic():alert=ProcurementAlert.objects.create(unit=intervention.unit,component_type=kind,message=(request.POST.get('message') or f'Necesidad de {kind.name}')[:500]);UnitAlertOrigin.objects.create(alert=alert,intervention=intervention,origin_worker=request.user,origin_zone=intervention.zone)
 messages.success(request,'Alerta registrada con origen de trabajador, zona, SN y Pedido.');return redirect('unit_workbench',intervention_pk=intervention.pk)
@login_required
@require_POST
def install_reservation(request,intervention_pk,reservation_pk):
 if not _can_work(request.user):return _deny()
 intervention=get_object_or_404(UnitIntervention,pk=intervention_pk);reservation=get_object_or_404(ComponentReservation,pk=reservation_pk,unit=intervention.unit)
 if reservation.status=='active':reservation.install(request.user);ReservationInstallation.objects.get_or_create(reservation=reservation,defaults={'intervention':intervention,'installed_by':request.user});messages.success(request,'Componente instalado. La reparación queda pendiente de confirmación.')
 return redirect('unit_workbench',intervention_pk=intervention.pk)
@login_required
@require_POST
def confirm_repair(request,intervention_pk,reservation_pk):
 if not _can_confirm(request.user):return _deny()
 intervention=get_object_or_404(UnitIntervention,pk=intervention_pk);reservation=get_object_or_404(ComponentReservation.objects.select_related('repair','component','component__component_kind'),pk=reservation_pk,unit=intervention.unit,status='installed')
 with transaction.atomic():
  RepairConfirmation.objects.get_or_create(repair=reservation.repair,defaults={'intervention':intervention,'confirmed_by':request.user,'observations':(request.POST.get('observations') or '').strip()});reservation.status='confirmed';reservation.resolved_at=timezone.now();reservation.save(update_fields=['status','resolved_at'])
  if reservation.component.component_kind_id:ProcurementAlert.objects.filter(unit=reservation.unit,component_type=reservation.component.component_kind,status='open').update(status='resolved',resolved_at=reservation.resolved_at)
 messages.success(request,'Reparación confirmada y trazabilidad cerrada.');return redirect('unit_workbench',intervention_pk=intervention.pk)
