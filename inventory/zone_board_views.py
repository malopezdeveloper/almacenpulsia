from collections import OrderedDict
from datetime import date
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.utils import timezone
from .models import ProductionZone
from .unit_workflow_models import UnitIntervention,PhysicalUnitLocation


def _parse_day(value, fallback):
    try:
        return date.fromisoformat((value or '').strip())
    except (TypeError, ValueError):
        return fallback


@login_required
def zone_boards(request):
    if not (request.user.is_staff or request.user.is_superuser):
        return HttpResponseForbidden('Solo Gestor y Administradores pueden consultar las Pizarras de Zona.')
    today=timezone.localdate()
    start=_parse_day(request.GET.get('start'),today)
    end=_parse_day(request.GET.get('end'),start)
    if start>end:start,end=end,start
    zones=list(ProductionZone.objects.filter(is_active=True).order_by('position','name'))
    boards=OrderedDict((z.pk,{'zone':z,'rows':[],'total':0,'currently_here':0}) for z in zones)
    qs=(UnitIntervention.objects.filter(created_at__date__range=(start,end))
        .select_related('unit','unit__order','worker','zone','destination_zone')
        .order_by('zone__position','zone__name','created_at','pk'))
    current_ids=set(PhysicalUnitLocation.objects.filter(zone_id__in=boards.keys()).values_list('intervention_id',flat=True))
    for i in qs:
        if i.zone_id not in boards:continue
        local_start=timezone.localtime(i.created_at)
        local_end=timezone.localtime(i.finished_at) if i.finished_at else None
        row={'intervention':i,'sn':i.unit.serial_number,'order':i.unit.order.name if i.unit.order_id else 'STOCK','worker':i.worker.get_full_name().strip() or i.worker.get_username(),'start':local_start,'finish':local_end,'duration_minutes':i.duration_minutes if i.finished_at else None,'is_current':i.pk in current_ids}
        boards[i.zone_id]['rows'].append(row);boards[i.zone_id]['total']+=1
        if row['is_current']:boards[i.zone_id]['currently_here']+=1
    return render(request,'inventory/zone_boards.html',{'boards':list(boards.values()),'start':start,'end':end,'today':today,'total_units':sum(b['total'] for b in boards.values())})
