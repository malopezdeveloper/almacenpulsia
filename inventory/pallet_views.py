from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import AuditLog, ProductionZone
from .pallet_models import Pallet, PalletUnit
from .unit_workflow_models import UnitIntervention, PhysicalUnitLocation


def _can_work(user):
    return user.is_authenticated and not getattr(getattr(user, 'inventory_profile', None), 'is_guest', False)


def _is_quality_zone(zone):
    text = f'{getattr(zone, "code", "")} {getattr(zone, "name", "")}'.casefold()
    return 'calidad' in text


def _can_quality(request):
    zone_id = request.session.get('pulsia_declared_zone_id')
    if not zone_id:
        return False
    zone = ProductionZone.objects.filter(pk=zone_id, is_active=True).first()
    return bool(zone and _is_quality_zone(zone))


@login_required
@require_POST
def declare_worker_zone(request):
    if not _can_work(request.user):
        return HttpResponseForbidden('No tienes permiso para esta operación.')
    zone = get_object_or_404(ProductionZone, pk=request.POST.get('zone_id'), is_active=True)
    request.session['pulsia_declared_zone_id'] = zone.pk
    request.session.modified = True
    return JsonResponse({'ok': True, 'zone_id': zone.pk, 'zone': zone.name, 'is_quality': _is_quality_zone(zone)})


@login_required
def pallet_center(request):
    if not _can_work(request.user):
        return HttpResponseForbidden('No tienes permiso para acceder a Palet / Enviado.')
    pallets = (Pallet.objects.prefetch_related('units__unit__order', 'units__unit__order__customer')
               .select_related('created_by', 'shipped_by').order_by('-id'))
    return render(request, 'inventory/pallets.html', {
        'pallets': pallets,
        'can_quality': _can_quality(request),
    })


@login_required
def open_pallets_api(request):
    if not _can_work(request.user):
        return HttpResponseForbidden('No tienes permiso para esta operación.')
    rows = []
    for p in Pallet.objects.filter(status=Pallet.STATUS_OPEN).order_by('-id'):
        rows.append({'id': p.pk, 'code': p.code, 'units': p.unit_count})
    return JsonResponse({'results': rows})


@login_required
@require_POST
def create_pallet(request):
    if not _can_quality(request):
        return HttpResponseForbidden('Sólo un usuario situado en Calidad puede crear palets.')
    pallet = Pallet.objects.create(created_by=request.user)
    AuditLog.objects.create(user=request.user, action='pallet_created', object_type='Pallet', object_id=str(pallet.pk), details={'code': pallet.code})
    messages.success(request, f'{pallet.code} creado. Puedes empezar a añadir unidades desde Calidad.')
    return redirect('pallet_center')


@login_required
@require_POST
def add_intervention_to_pallet(request, intervention_pk):
    if not _can_work(request.user):
        return HttpResponseForbidden('No tienes permiso para esta operación.')
    if not _can_quality(request):
        return JsonResponse({'ok': False, 'error': 'Sólo Calidad puede enviar unidades a Palet / Enviado.'}, status=403)
    pallet = get_object_or_404(Pallet, pk=request.POST.get('pallet_id'), status=Pallet.STATUS_OPEN)
    with transaction.atomic():
        intervention = get_object_or_404(
            UnitIntervention.objects.select_for_update().select_related('unit', 'unit__physical_unit', 'zone'),
            pk=intervention_pk, worker=request.user, finished_at__isnull=True,
        )
        if not _is_quality_zone(intervention.zone):
            return JsonResponse({'ok': False, 'error': 'Sólo una unidad que esté en Calidad puede pasar a Palet / Enviado.'}, status=409)
        if hasattr(intervention.unit, 'pallet_membership'):
            return JsonResponse({'ok': False, 'error': 'La unidad ya pertenece a un palet.'}, status=409)

        now = timezone.now()
        intervention.finished_at = now
        intervention.duration_seconds = max(0, int((now - intervention.created_at).total_seconds()))
        snapshot = dict(intervention.source_snapshot or {})
        snapshot.update({'logistic_destination': 'pallet', 'pallet_id': pallet.pk, 'pallet_code': pallet.code})
        intervention.source_snapshot = snapshot
        intervention.save(update_fields=['finished_at', 'duration_seconds', 'source_snapshot'])

        membership = PalletUnit.objects.create(pallet=pallet, unit=intervention.unit, added_by=request.user)
        PhysicalUnitLocation.objects.filter(physical_unit=intervention.unit.physical_unit, intervention=intervention).delete()
        AuditLog.objects.create(
            user=request.user,
            action='unit_added_to_pallet',
            object_type='PalletUnit',
            object_id=str(membership.pk),
            details={'serial_number': intervention.unit.serial_number, 'unit_id': intervention.unit_id,
                     'order_id': intervention.unit.order_id, 'pallet_id': pallet.pk, 'pallet_code': pallet.code},
        )
    return JsonResponse({'ok': True, 'pallet_id': pallet.pk, 'pallet_code': pallet.code})


@login_required
@require_POST
def remove_unit_from_pallet(request, membership_pk):
    if not _can_quality(request):
        return HttpResponseForbidden('Sólo Calidad puede modificar un palet abierto.')
    with transaction.atomic():
        membership = get_object_or_404(PalletUnit.objects.select_for_update().select_related('pallet', 'unit'), pk=membership_pk)
        if membership.pallet.status != Pallet.STATUS_OPEN:
            messages.error(request, 'Un palet enviado ya no puede modificarse.')
            return redirect('pallet_center')
        data = {'serial_number': membership.unit.serial_number, 'unit_id': membership.unit_id,
                'order_id': membership.unit.order_id, 'pallet_id': membership.pallet_id, 'pallet_code': membership.pallet.code}
        pallet_code = membership.pallet.code
        membership.delete()
        AuditLog.objects.create(user=request.user, action='unit_removed_from_pallet', object_type='PalletUnit', object_id=str(membership_pk), details=data)
    messages.success(request, f'Unidad retirada de {pallet_code}.')
    return redirect('pallet_center')


@login_required
@require_POST
def ship_pallet(request, pallet_pk):
    if not _can_quality(request):
        return HttpResponseForbidden('Sólo Calidad puede enviar palets.')
    with transaction.atomic():
        pallet = get_object_or_404(Pallet.objects.select_for_update(), pk=pallet_pk, status=Pallet.STATUS_OPEN)
        if not pallet.units.exists():
            messages.error(request, 'No se puede enviar un palet vacío.')
            return redirect('pallet_center')
        recipient = (request.POST.get('recipient') or '').strip()
        shipped_text = (request.POST.get('shipped_at') or '').strip()
        if not recipient or not shipped_text:
            messages.error(request, 'Para enviar el palet debes indicar fecha de envío y destinatario.')
            return redirect('pallet_center')
        try:
            naive = datetime.fromisoformat(shipped_text)
            shipped_at = timezone.make_aware(naive, timezone.get_current_timezone()) if timezone.is_naive(naive) else naive
        except ValueError:
            messages.error(request, 'La fecha de envío no es válida.')
            return redirect('pallet_center')

        names = request.POST.getlist('extra_name')
        values = request.POST.getlist('extra_value')
        extra = {}
        for name, value in zip(names, values):
            name = (name or '').strip()
            value = (value or '').strip()
            if name:
                extra[name] = value

        pallet.status = Pallet.STATUS_SHIPPED
        pallet.shipped_at = shipped_at
        pallet.recipient = recipient
        pallet.shipping_data = extra
        pallet.shipped_by = request.user
        pallet.save(update_fields=['status', 'shipped_at', 'recipient', 'shipping_data', 'shipped_by'])
        AuditLog.objects.create(
            user=request.user, action='pallet_shipped', object_type='Pallet', object_id=str(pallet.pk),
            details={'code': pallet.code, 'recipient': recipient, 'shipped_at': shipped_at.isoformat(),
                     'shipping_data': extra, 'unit_ids': list(pallet.units.values_list('unit_id', flat=True))},
        )
    messages.success(request, f'{pallet.code} marcado como enviado.')
    return redirect('pallet_center')
