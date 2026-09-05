from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import AuditLog
from .order_models import ComponentReservation, ProcurementAlert
from .unit_workflow_models import UnitIntervention, RepairConfirmation
from .permissions import user_is_manager


def _can_confirm(user, reservation, intervention):
    if not getattr(user, 'is_authenticated', False):
        return False
    if user_is_manager(user) or user.is_superuser or user.is_staff:
        return True
    # El técnico que reservó/instaló la pieza o el técnico de la intervención
    # puede probarla y confirmar el resultado sin permisos administrativos.
    return user.pk in {
        reservation.technician_id,
        reservation.installed_by_id,
        intervention.worker_id,
    }


@login_required
@require_POST
def confirm_installation(request, intervention_pk, reservation_pk):
    # La intervención puede estar terminada: confirmar una prueba posterior no
    # debe devolver 404 sólo porque finished_at ya tenga valor.
    intervention = get_object_or_404(
        UnitIntervention.objects.select_related('unit', 'worker'),
        pk=intervention_pk,
    )
    reservation = get_object_or_404(
        ComponentReservation.objects.select_related(
            'repair', 'component', 'component__component_kind', 'technician', 'installed_by'
        ),
        pk=reservation_pk,
        unit=intervention.unit,
        status='installed',
    )
    if not _can_confirm(request.user, reservation, intervention):
        return HttpResponseForbidden('Sólo el técnico implicado o un responsable puede confirmar esta instalación.')
    if reservation.repair_id is None:
        messages.error(request, 'La instalación no tiene una reparación asociada y no puede confirmarse.')
        return redirect(f'/produccion/intervencion/{intervention.pk}/?mode=installation')

    now = timezone.now()
    with transaction.atomic():
        reservation = ComponentReservation.objects.select_for_update().get(pk=reservation.pk)
        if reservation.status != 'installed':
            messages.info(request, 'Esta instalación ya no está pendiente de confirmación.')
            return redirect(f'/produccion/intervencion/{intervention.pk}/?mode=installation')

        RepairConfirmation.objects.get_or_create(
            repair_id=reservation.repair_id,
            defaults={
                'intervention': intervention,
                'confirmed_by': request.user,
                'observations': 'Instalación probada y confirmada OK por el técnico.',
            },
        )
        reservation.status = 'confirmed'
        reservation.resolved_at = now
        reservation.save(update_fields=['status', 'resolved_at'])

        # Resolver automáticamente las alertas abiertas del mismo tipo de
        # componente. Si el componente no tiene ComponentType enlazado no se
        # resuelven alertas ambiguas automáticamente.
        kind_id = reservation.component.component_kind_id
        resolved_alerts = 0
        if kind_id:
            alerts = ProcurementAlert.objects.select_for_update().filter(
                unit=reservation.unit,
                component_type_id=kind_id,
                status='open',
            )
            resolved_alerts = alerts.count()
            alerts.update(status='resolved', resolved_at=now)

        AuditLog.objects.create(
            user=request.user,
            action='component_installation_confirmed',
            object_type='ComponentReservation',
            object_id=str(reservation.pk),
            details={
                'serial_number': reservation.unit_serial_number,
                'intervention_id': intervention.pk,
                'repair_id': reservation.repair_id,
                'component_id': reservation.component_id,
                'component_type': reservation.component.component_type,
                'resolved_alerts': resolved_alerts,
                'intervention_already_finished': bool(intervention.finished_at),
            },
        )

    messages.success(
        request,
        'Instalación probada y confirmada OK. La reserva queda resuelta y la pieza permanece instalada.'
    )
    return redirect(f'/produccion/intervencion/{intervention.pk}/?mode=installation')
