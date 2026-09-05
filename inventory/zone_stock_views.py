from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import AuditLog, ProductionZone
from .permissions import user_is_manager
from .unit_workflow_models import UnitIntervention, PhysicalUnitLocation


def _zone_matches(zone, word):
    text = f'{getattr(zone, "code", "")} {getattr(zone, "name", "")}'.casefold()
    return word.casefold() in text


def _can_view_stock(user):
    return bool(user.is_authenticated and (user.is_staff or user_is_manager(user)))


def _can_work(user):
    return user.is_authenticated and not getattr(getattr(user, 'inventory_profile', None), 'is_guest', False)


def _finish_error(request, text, status=409):
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'ok': False, 'error': text}, status=status)
    messages.error(request, text)
    return redirect('production_board')


@login_required
def zone_stock(request):
    if not _can_view_stock(request.user):
        return HttpResponseForbidden('Sólo Administradores y Gestor pueden consultar el stock de zonas.')

    zones = list(ProductionZone.objects.filter(is_active=True).order_by('position', 'name'))
    selected = (request.GET.get('zone') or '').strip()
    locations = (PhysicalUnitLocation.objects
                 .select_related('zone', 'unit', 'unit__order', 'unit__order__customer', 'worker',
                                 'intervention', 'intervention__zone', 'intervention__destination_zone')
                 .order_by('zone__position', 'zone__name', 'unit__serial_number'))
    if selected.isdigit():
        locations = locations.filter(zone_id=int(selected))

    by_zone = {z.pk: [] for z in zones}
    for loc in locations:
        intervention = loc.intervention
        destination = intervention.destination_zone if intervention and intervention.finished_at else None
        by_zone.setdefault(loc.zone_id, []).append({
            'location': loc,
            'unit': loc.unit,
            'order': loc.unit.order,
            'working': bool(intervention and not intervention.finished_at),
            'recommended': destination,
            'source_zone': intervention.zone if intervention else None,
        })

    zone_rows = []
    for zone in zones:
        rows = by_zone.get(zone.pk, [])
        zone_rows.append({'zone': zone, 'rows': rows, 'count': len(rows)})

    return render(request, 'inventory/zone_stock.html', {
        'zone_rows': zone_rows,
        'selected_zone': int(selected) if selected.isdigit() else None,
        'total_units': sum(x['count'] for x in zone_rows),
    })


@login_required
@require_POST
def finish_unit_intervention(request, intervention_pk):
    """Finaliza el trabajo y mueve físicamente la unidad al destino elegido.

    Mientras una intervención está abierta, la ubicación física es la zona/origen
    donde trabaja el técnico. Al finalizar, destination_zone pasa a ser la nueva
    ubicación física. Secadero mantiene la restricción especial: sólo Pintura
    puede introducir unidades allí.
    """
    if not _can_work(request.user):
        return HttpResponseForbidden('No tienes permiso para esta operación.')

    with transaction.atomic():
        intervention = get_object_or_404(
            UnitIntervention.objects.select_for_update().select_related(
                'unit', 'unit__physical_unit', 'zone', 'destination_zone'),
            pk=intervention_pk, worker=request.user, finished_at__isnull=True,
        )
        destination = get_object_or_404(
            ProductionZone, pk=request.POST.get('destination_zone'), is_active=True)

        if destination.pk == intervention.zone_id:
            return _finish_error(request, 'El destino debe ser distinto de la zona actual.')

        is_dryer = _zone_matches(destination, 'secadero')
        is_paint = _zone_matches(intervention.zone, 'pintura')
        if is_dryer and not is_paint:
            return _finish_error(request, 'Sólo Pintura puede enviar una unidad a Secadero.', 403)

        now = timezone.now()
        intervention.finished_at = now
        intervention.duration_seconds = max(0, int((now - intervention.created_at).total_seconds()))
        intervention.destination_zone = destination
        intervention.save(update_fields=['finished_at', 'duration_seconds', 'destination_zone'])

        physical = intervention.unit.physical_unit
        location = (PhysicalUnitLocation.objects.select_for_update()
                    .filter(physical_unit=physical).first())
        if location:
            location.unit = intervention.unit
            location.zone = destination
            location.intervention = intervention
            location.worker = request.user
            location.entered_at = now
            location.save(update_fields=['unit', 'zone', 'intervention', 'worker', 'entered_at', 'updated_at'])
        else:
            PhysicalUnitLocation.objects.create(
                physical_unit=physical, unit=intervention.unit, zone=destination,
                intervention=intervention, worker=request.user, entered_at=now,
            )

        AuditLog.objects.create(
            user=request.user, action='unit_moved_to_destination', object_type='OrderUnit', object_id=str(intervention.unit_id),
            details={
                'serial_number': intervention.unit.serial_number,
                'intervention_id': intervention.pk,
                'source_zone_id': intervention.zone_id,
                'source_zone': intervention.zone.name,
                'destination_zone_id': destination.pk,
                'destination_zone': destination.name,
                'physical_zone_id': destination.pk,
                'physical_zone': destination.name,
            },
        )

    messages.success(
        request,
        f'{intervention.unit.serial_number}: trabajo finalizado en {intervention.zone.name}; enviada al stock de {destination.name}.',
    )
    return redirect('production_board')


@login_required
@require_POST
def delete_unit_intervention(request, intervention_pk):
    """No permite borrar la intervención que actualmente sostiene el stock físico."""
    if not _can_work(request.user):
        return HttpResponseForbidden('No tienes permiso para esta operación.')
    with transaction.atomic():
        intervention = get_object_or_404(
            UnitIntervention.objects.select_for_update().select_related('unit', 'unit__physical_unit', 'zone'),
            pk=intervention_pk, worker=request.user,
        )
        if PhysicalUnitLocation.objects.filter(intervention=intervention).exists():
            text = 'No se puede borrar esta fila porque define la ubicación física actual de la unidad en el stock de una zona.'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'ok': False, 'error': text}, status=409)
            messages.error(request, text)
            return redirect('production_board')
        if intervention.alerts.exists() or intervention.component_installations.exists() or intervention.repair_confirmations.exists():
            text = 'Esta fila ya tiene trazabilidad asociada y no puede borrarse.'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'ok': False, 'error': text}, status=409)
            messages.error(request, text)
            return redirect('production_board')
        details = {
            'serial_number': intervention.unit.serial_number,
            'intervention_id': intervention.pk,
            'unit_id': intervention.unit_id,
            'order_id': intervention.unit.order_id,
            'zone': intervention.zone.name,
            'started_at': intervention.created_at.isoformat(),
            'finished_at': intervention.finished_at.isoformat() if intervention.finished_at else None,
            'duration_seconds': intervention.duration_seconds,
            'source': intervention.source,
            'source_snapshot': intervention.source_snapshot,
        }
        serial = intervention.unit.serial_number
        AuditLog.objects.create(user=request.user, action='unit_board_row_deleted', object_type='UnitIntervention', object_id=str(intervention.pk), details=details)
        intervention.delete()
    return JsonResponse({'ok': True, 'serial_number': serial})
