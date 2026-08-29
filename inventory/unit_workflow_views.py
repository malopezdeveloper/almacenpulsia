from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse,HttpResponseForbidden
from django.shortcuts import get_object_or_404,redirect,render
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import ProductionModelMySQLSource,ProductionZone
from .order_models import CustomerOrder,OrderUnit,PhysicalUnit,ComponentType,ProcurementAlert,ComponentReservation
from .external_mysql import find_aiken_unit_exact
from .unit_workflow_models import UnitIntervention,UnitAlertOrigin,ReservationInstallation,RepairConfirmation
from .permissions import user_has_permission

def _can_work(u):return u.is_authenticated and not getattr(getattr(u,'inventory_profile',None),'is_guest',False)
def _can_confirm(u):return u.is_superuser or user_has_permission(u,'repairs.manage') or user_has_permission(u,'components.reserve') or u.is_staff
def _deny():return HttpResponseForbidden('No tienes permiso para esta operación.')
def _local_cycle(sn):return OrderUnit.objects.select_related('order','order__customer','physical_unit').filter(serial_number__iexact=sn).order_by('-imported_at','-pk').first()
def _snapshot(u):return {'serial_number':u.serial_number,'order_id':u.order_id,'order':u.order.name,'brand':u.brand,'model':u.model,'processor':u.processor,'ram':u.ram,'disk':u.disk,'aiken_lot':u.aiken_lot,'aiken_unit_id':u.aiken_unit_id}
def _value(r,n,f=''):return (r.POST.get(n) if n in r.POST else f) or ''
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
def my_open_interventions(request):
 if not _can_work(request.user):return _deny()
 now=timezone.now()
 rows=[]
 qs=UnitIntervention.objects.filter(worker=request.user,finished_at__isnull=True).select_related('unit','unit__order','zone').order_by('created_at','pk')
 for i in qs:
  rows.append({'id':i.pk,'serial_number':i.unit.serial_number,'order':i.unit.order.name if i.unit.order_id else 'STOCK','zone':i.zone.name,'zone_id':i.zone_id,'started_at':timezone.localtime(i.created_at).strftime('%d/%m/%Y %H:%M:%S'),'elapsed_seconds':max(0,int((now-i.created_at).total_seconds())),'url':f'/produccion/intervencion/{i.pk}/'})
 return JsonResponse({'results':rows})
@login_required
@require_POST
def start_unit_intervention(request):
 if not _can_work(request.user):return _deny()
 sn=(request.POST.get('serial_number') or '').strip();origin=get_object_or_404(ProductionZone,pk=request.POST.get('origin_zone') or request.POST.get('zone'),is_active=True)
 if not sn:return redirect('production_board')
 unit=_local_cycle(sn);source_name='local';extra={}
 if not unit:
  source=ProductionModelMySQLSource.objects.order_by('-updated_at').first();row=None
  if source:
   try:row=find_aiken_unit_exact(source,sn)
   except Exception:row=None
  if row:
   if not request.POST.get('order'):return render(request,'inventory/unit_intervention_confirm.html',{'serial_number':sn,'zone':origin,'source':'aiken','aiken':row,'orders':CustomerOrder.objects.filter(status='open').order_by('-id')})
   order=get_object_or_404(CustomerOrder,pk=request.POST['order'],status='open');original={k:str(row.get(k) or '') for k in ('brand','model','processor','ram','disk','lot','id')};vals={k:_value(request,k,original[k]).strip() for k in ('brand','model','processor','ram','disk')};lot=_value(request,'aiken_lot',original['lot'] or order.lot).strip();physical,_=PhysicalUnit.objects.get_or_create(serial_number=sn,defaults=vals);unit,_=OrderUnit.objects.get_or_create(order=order,physical_unit=physical,defaults={'serial_number':sn,'aiken_lot':lot,'aiken_unit_id':original['id'],**vals});source_name='aiken';extra={'aiken_original':original,'worker_values':dict(vals,lot=lot)}
  else:
   if request.POST.get('confirm_manual')!='yes':return render(request,'inventory/unit_intervention_confirm.html',{'serial_number':sn,'zone':origin,'source':'manual','orders':CustomerOrder.objects.filter(status='open').order_by('-id')})
   order=get_object_or_404(CustomerOrder,pk=request.POST.get('order'),status='open');vals={k:_value(request,k).strip() for k in ('brand','model','processor','ram','disk')};physical,_=PhysicalUnit.objects.get_or_create(serial_number=sn,defaults=vals);unit,_=OrderUnit.objects.get_or_create(order=order,physical_unit=physical,defaults={'serial_number':sn,**vals});source_name='manual'
 existing=UnitIntervention.objects.filter(unit=unit,worker=request.user,finished_at__isnull=True).first()
 if existing:messages.info(request,f'{sn} ya estaba pendiente en tu Pizarra.');return redirect('production_board')
 snap=_snapshot(unit);snap.update(extra);UnitIntervention.objects.create(unit=unit,worker=request.user,zone=origin,source=source_name,source_snapshot=snap);messages.success(request,f'{sn} añadida a tu Pizarra. El tiempo empieza a contar ahora.');return redirect('production_board')
@login_required
def unit_workbench(request,intervention_pk):
 i=get_object_or_404(UnitIntervention.objects.select_related('unit','unit__order','unit__order__customer','worker','zone','destination_zone'),pk=intervention_pk)
 if not _can_work(request.user):return _deny()
 u=i.unit;return render(request,'inventory/unit_workbench.html',{'intervention':i,'unit':u,'zones':ProductionZone.objects.filter(is_active=True).exclude(pk=i.zone_id).order_by('position','name'),'alerts':u.procurement_alerts.select_related('component_type').order_by('-created_at'),'reservations':u.component_reservations.select_related('component','technician','installed_by','repair').order_by('-reserved_at'),'component_types':ComponentType.objects.filter(active=True).order_by('name'),'can_confirm':_can_confirm(request.user)})
@login_required
@require_POST
def finish_unit_intervention(request,intervention_pk):
 if not _can_work(request.user):return _deny()
 with transaction.atomic():
  i=get_object_or_404(UnitIntervention.objects.select_for_update().select_related('unit','zone'),pk=intervention_pk,worker=request.user,finished_at__isnull=True);dest=get_object_or_404(ProductionZone,pk=request.POST.get('destination_zone'),is_active=True)
  if dest.pk==i.zone_id:
   messages.error(request,'La zona de destino debe ser distinta de la zona en la que estás trabajando.');return redirect('unit_workbench',intervention_pk=i.pk)
  now=timezone.now();i.destination_zone=dest;i.finished_at=now;i.duration_seconds=max(0,int((now-i.created_at).total_seconds()));i.save(update_fields=['destination_zone','finished_at','duration_seconds'])
 messages.success(request,f'{i.unit.serial_number} terminada: {i.zone.name} → {dest.name}. Tiempo invertido: {i.duration_minutes} min.');return redirect('production_board')
@login_required
@require_POST
def create_unit_alert(request,intervention_pk):
 if not _can_work(request.user):return _deny()
 i=get_object_or_404(UnitIntervention.objects.select_related('unit','zone'),pk=intervention_pk,finished_at__isnull=True);kind=get_object_or_404(ComponentType,pk=request.POST.get('component_type'),active=True);alert=ProcurementAlert.objects.create(unit=i.unit,component_type=kind,message=(request.POST.get('message') or f'Necesidad de {kind.name}')[:500]);UnitAlertOrigin.objects.create(alert=alert,intervention=i,origin_worker=request.user,origin_zone=i.zone);messages.success(request,'Alerta creada. La unidad puede continuar a otra zona con la alerta abierta.');return redirect('unit_workbench',intervention_pk=i.pk)
@login_required
@require_POST
def install_reservation(request,intervention_pk,reservation_pk):
 if not _can_work(request.user):return _deny()
 i=get_object_or_404(UnitIntervention,pk=intervention_pk,finished_at__isnull=True);r=get_object_or_404(ComponentReservation,pk=reservation_pk,unit=i.unit)
 if r.status=='active':r.install(request.user);ReservationInstallation.objects.get_or_create(reservation=r,defaults={'intervention':i,'installed_by':request.user})
 return redirect('unit_workbench',intervention_pk=i.pk)
@login_required
@require_POST
def confirm_repair(request,intervention_pk,reservation_pk):
 if not _can_confirm(request.user):return _deny()
 i=get_object_or_404(UnitIntervention,pk=intervention_pk,finished_at__isnull=True);r=get_object_or_404(ComponentReservation.objects.select_related('repair','component','component__component_kind'),pk=reservation_pk,unit=i.unit,status='installed');RepairConfirmation.objects.get_or_create(repair=r.repair,defaults={'intervention':i,'confirmed_by':request.user});return redirect('unit_workbench',intervention_pk=i.pk)