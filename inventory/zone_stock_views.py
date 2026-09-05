from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import AuditLog, ProductionZone
from .permissions import user_is_manager
from .unit_workflow_models import UnitIntervention, PhysicalUnitLocation


def _zone_matches(zone, word):
    text = f'{getattr(zone, "code", "")} {getattr(zone, "name", "")}'.casefold()
    return word.casefold() in text


def _can_view_stock(user): return bool(user.is_authenticated and (user.is_staff or user_is_manager(user)))
def _can_work(user): return user.is_authenticated and not getattr(getattr(user, 'inventory_profile', None), 'is_guest', False)
def _ajax(request): return request.headers.get('X-Requested-With') == 'XMLHttpRequest'
def _finish_error(request,text,status=409):
    if _ajax(request): return JsonResponse({'ok':False,'error':text},status=status)
    messages.error(request,text);return redirect('production_board')

def _is_warranty_unit(unit):
    return bool(unit and unit.order and unit.order.name.strip().casefold() in ('garantías','garantias'))

@login_required
def zone_stock(request):
    if not _can_view_stock(request.user):return HttpResponseForbidden('Sólo Administradores y Gestor pueden consultar el stock de zonas.')
    zones=list(ProductionZone.objects.filter(is_active=True).order_by('position','name'));selected=(request.GET.get('zone') or '').strip()
    locations=(PhysicalUnitLocation.objects.select_related('zone','unit','unit__order','unit__order__customer','worker','intervention','intervention__zone','intervention__destination_zone').order_by('zone__position','zone__name','unit__serial_number'))
    if selected.isdigit():locations=locations.filter(zone_id=int(selected))
    by_zone={z.pk:[] for z in zones}
    for loc in locations:
        intervention=loc.intervention;destination=intervention.destination_zone if intervention and intervention.finished_at else None
        by_zone.setdefault(loc.zone_id,[]).append({'location':loc,'unit':loc.unit,'order':loc.unit.order,'working':bool(intervention and not intervention.finished_at),'recommended':destination,'source_zone':intervention.zone if intervention else None})
    zone_rows=[{'zone':z,'rows':by_zone.get(z.pk,[]),'count':len(by_zone.get(z.pk,[]))} for z in zones]
    return render(request,'inventory/zone_stock.html',{'zone_rows':zone_rows,'selected_zone':int(selected) if selected.isdigit() else None,'total_units':sum(x['count'] for x in zone_rows)})

@login_required
@require_POST
def finish_unit_intervention(request,intervention_pk):
    if not _can_work(request.user):return _finish_error(request,'No tienes permiso para esta operación.',403)
    try:
        with transaction.atomic():
            intervention=(UnitIntervention.objects.select_for_update().select_related('unit','unit__order','unit__physical_unit','zone').filter(pk=intervention_pk,worker=request.user).first())
            if intervention is None:return _finish_error(request,'La intervención no existe o pertenece a otro técnico.',404)
            if intervention.finished_at:return _finish_error(request,'Esta unidad ya estaba finalizada. Recarga la pizarra.',409)
            destination_id=(request.POST.get('destination_zone') or '').strip();destination=None
            if destination_id:
                if not destination_id.isdigit():return _finish_error(request,'El destino recibido no es válido.',400)
                destination=ProductionZone.objects.filter(pk=int(destination_id),is_active=True).first()
                if destination is None:return _finish_error(request,'La zona de destino ya no existe o está desactivada.',409)
                if destination.pk==intervention.zone_id:destination=None
            # Garantías sólo acepta retornos de unidades cuyo ciclo actual pertenece al
            # pedido permanente GARANTÍAS. Las altas excepcionales se hacen al fichar
            # por Responsable de Garantías/Gestor, nunca mediante un destino normal.
            if destination is not None and _zone_matches(destination,'garant') and not _is_warranty_unit(intervention.unit):
                return _finish_error(request,'Esta unidad no pertenece al pedido GARANTÍAS y no puede enviarse a Garantías.',403)
            if destination is not None and _zone_matches(destination,'secadero') and not _zone_matches(intervention.zone,'pintura'):
                return _finish_error(request,'Sólo Pintura puede enviar una unidad a Secadero.',403)
            physical_zone=destination or intervention.zone;now=timezone.now();intervention.finished_at=now;intervention.duration_seconds=max(0,int((now-intervention.created_at).total_seconds()));intervention.destination_zone=destination;intervention.save(update_fields=['finished_at','duration_seconds','destination_zone'])
            location=PhysicalUnitLocation.objects.select_for_update().filter(physical_unit_id=intervention.unit.physical_unit_id).first()
            if location is None:location=PhysicalUnitLocation(physical_unit_id=intervention.unit.physical_unit_id,unit=intervention.unit,zone=physical_zone,intervention=intervention,worker=request.user,entered_at=now)
            else:location.unit=intervention.unit;location.zone=physical_zone;location.intervention=intervention;location.worker=request.user;location.entered_at=now
            location.save()
            AuditLog.objects.create(user=request.user,action='unit_moved_to_destination' if destination else 'unit_finished_in_origin',object_type='OrderUnit',object_id=str(intervention.unit_id),details={'serial_number':intervention.unit.serial_number,'intervention_id':intervention.pk,'source_zone_id':intervention.zone_id,'source_zone':intervention.zone.name,'destination_zone_id':destination.pk if destination else None,'destination_zone':destination.name if destination else None,'physical_zone_id':physical_zone.pk,'physical_zone':physical_zone.name,'warranty_cycle':_is_warranty_unit(intervention.unit)})
    except Exception as exc:
        if _ajax(request):return JsonResponse({'ok':False,'error':f'Error al finalizar: {exc.__class__.__name__}: {exc}'},status=500)
        raise
    success_text=(f'{intervention.unit.serial_number}: trabajo finalizado en {intervention.zone.name}; enviada al stock de {destination.name}.' if destination else f'{intervention.unit.serial_number}: trabajo finalizado; permanece en el stock de {intervention.zone.name}.')
    if _ajax(request):return JsonResponse({'ok':True,'serial_number':intervention.unit.serial_number,'intervention_id':intervention.pk,'destination_zone_id':destination.pk if destination else None,'destination_zone':destination.name if destination else '','physical_zone_id':physical_zone.pk,'physical_zone':physical_zone.name,'message':success_text})
    messages.success(request,success_text);return redirect('production_board')

@login_required
@require_POST
def delete_unit_intervention(request,intervention_pk):
    if not _can_work(request.user):return HttpResponseForbidden('No tienes permiso para esta operación.')
    try:
        with transaction.atomic():
            intervention=(UnitIntervention.objects.select_for_update().select_related('unit','unit__physical_unit','zone').filter(pk=intervention_pk,worker=request.user).first())
            if intervention is None:return JsonResponse({'ok':False,'error':'La intervención no existe o pertenece a otro técnico.'},status=404)
            if intervention.alerts.exists() or intervention.component_installations.exists() or intervention.repair_confirmations.exists():return JsonResponse({'ok':False,'error':'Esta fila ya tiene trazabilidad asociada y no puede borrarse.'},status=409)
            details={'serial_number':intervention.unit.serial_number,'intervention_id':intervention.pk,'unit_id':intervention.unit_id,'order_id':intervention.unit.order_id,'zone':intervention.zone.name,'started_at':intervention.created_at.isoformat(),'finished_at':intervention.finished_at.isoformat() if intervention.finished_at else None,'duration_seconds':intervention.duration_seconds,'source':intervention.source,'source_snapshot':intervention.source_snapshot,'removed_current_location':False};serial=intervention.unit.serial_number
            current_location=PhysicalUnitLocation.objects.select_for_update().filter(intervention=intervention).first()
            if current_location:details['removed_current_location']=True;details['physical_zone_id']=current_location.zone_id;details['physical_zone']=current_location.zone.name;current_location.delete()
            AuditLog.objects.create(user=request.user,action='unit_board_row_deleted',object_type='UnitIntervention',object_id=str(intervention.pk),details=details);intervention.delete()
    except Exception as exc:return JsonResponse({'ok':False,'error':f'Error al borrar: {exc.__class__.__name__}: {exc}'},status=500)
    return JsonResponse({'ok':True,'serial_number':serial,'removed_current_location':details['removed_current_location']})
