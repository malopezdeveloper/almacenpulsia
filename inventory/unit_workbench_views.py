from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, render

from .models import ProductionZone
from .order_models import OrderUnit, ComponentType, ProcurementAlert, ComponentReservation
from .permissions import user_has_permission
from .unit_workflow_models import UnitIntervention


def _can_work(user):
    return user.is_authenticated and not getattr(getattr(user, 'inventory_profile', None), 'is_guest', False)


def _can_confirm(user):
    return (
        user.is_superuser
        or user.is_staff
        or user_has_permission(user, 'repairs.manage')
        or user_has_permission(user, 'components.reserve')
    )


@login_required
def unit_workbench(request, intervention_pk):
    """Workbench scoped to the physical machine selected on Mi Pizarra.

    Alerts and reservations follow the physical unit/SN across order cycles, but
    never leak records belonging to another machine.
    """
    intervention = get_object_or_404(
        UnitIntervention.objects.select_related(
            'unit',
            'unit__physical_unit',
            'unit__order',
            'unit__order__customer',
            'worker',
            'zone',
            'destination_zone',
        ),
        pk=intervention_pk,
    )
    if not _can_work(request.user):
        return HttpResponseForbidden('No tienes permiso para esta operación.')

    mode = (request.GET.get('mode') or 'summary').strip().lower()
    if mode not in ('summary', 'alerts', 'installation'):
        mode = 'summary'

    unit = intervention.unit
    if unit.physical_unit_id:
        cycle_ids = OrderUnit.objects.filter(
            physical_unit_id=unit.physical_unit_id
        ).values_list('pk', flat=True)
    else:
        cycle_ids = OrderUnit.objects.filter(
            serial_number__iexact=unit.serial_number
        ).values_list('pk', flat=True)

    alerts = (
        ProcurementAlert.objects
        .filter(unit_id__in=cycle_ids)
        .select_related('component_type', 'unit')
        .order_by('-created_at')
    )
    reservations = (
        ComponentReservation.objects
        .filter(unit_id__in=cycle_ids)
        .select_related('component', 'technician', 'installed_by', 'repair', 'unit')
        .order_by('-reserved_at')
    )

    return render(
        request,
        'inventory/unit_workbench.html',
        {
            'mode': mode,
            'intervention': intervention,
            'unit': unit,
            'zones': ProductionZone.objects.filter(is_active=True)
                .exclude(pk=intervention.zone_id)
                .order_by('position', 'name'),
            'alerts': alerts,
            'reservations': reservations,
            'component_types': ComponentType.objects.filter(active=True).order_by('name'),
            'can_confirm': _can_confirm(request.user),
        },
    )
