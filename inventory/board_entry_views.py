from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import ProductionModelMySQLSource, ProductionZone, AuditLog
from .order_models import CustomerOrder, OrderUnit, PhysicalUnit
from .external_mysql import find_aiken_unit_exact
from .unit_workflow_models import UnitIntervention, PhysicalUnitLocation
from .pallet_models import Pallet, PalletUnit
from .permissions import user_has_permission

UNIT_FIELDS = ('brand', 'model', 'processor', 'ram', 'disk')


def _can_work(user):
    return user.is_authenticated and not getattr(getattr(user, 'inventory_profile', None), 'is_guest', False)


def _can_manual_edit(user):
    # La edición manual de ficha queda reservada a Gestor/Administradores.
    return user.is_superuser or user.is_staff or user_has_permission(user, 'orders.manage')


def _clean(value):
    return ' '.join(str(value or '').strip().split())


def _aiken_exact(sn):
    source = ProductionModelMySQLSource.objects.order_by('-updated_at').first()
    if not source:
        return None
    try:
        return find_aiken_unit_exact(source, sn)
    except Exception:
        return None


def _close(intervention, now, destination=None):
    if intervention.finished_at:
        return
    intervention.finished_at = now
    intervention.duration_seconds = max(0, int((now - intervention.created_at).total_seconds()))
    if destination is not None:
        intervention.destination_zone = destination
    intervention.save(update_fields=['finished_at', 'duration_seconds', 'destination_zone'])


@login_required
def board_serial_suggestions(request):
    """Autocompletado rápido y contextual: sólo unidades del pedido seleccionado."""
    if not _can_work(request.user):
        return HttpResponseForbidden('No tienes permiso para esta operación.')
    q = (request.GET.get('q') or '').strip()
    context = (request.GET.get('work_order') or '').strip()
    if len(q) < 1 or context == 'stock':
        return JsonResponse({'results': []})
    try:
        order_id = int(context)
    except (TypeError, ValueError):
        return JsonResponse({'results': []})
    order = CustomerOrder.objects.filter(pk=order_id, status='open').first()
    if not order:
        return JsonResponse({'results': []})
    units = (OrderUnit.objects.filter(order=order, serial_number__istartswith=q)
             .select_related('physical_unit').order_by('serial_number')[:40])
    return JsonResponse({'results': [
        {
            'id': u.pk,
            'serial_number': u.serial_number,
            'brand': u.brand,
            'model': u.model,
            'processor': u.processor,
            'ram': u.ram,
            'disk': u.disk,
        } for u in units
    ]})


@login_required
@require_POST
def board_start_unit(request):
    """Añade a pizarra. En pedido, un SN nuevo entra automáticamente en ese pedido."""
    if not _can_work(request.user):
        return HttpResponseForbidden('No tienes permiso para esta operación.')
    sn = (request.POST.get('serial_number') or '').strip()
    if not sn:
        return redirect('production_board')
    origin = get_object_or_404(ProductionZone, pk=request.POST.get('origin_zone') or request.POST.get('zone'), is_active=True)
    context = (request.POST.get('work_order') or 'stock').strip()
    selected_order = None
    unit = None
    source_name = 'local'
    aiken_row = None

    if context != 'stock':
        try:
            selected_order = CustomerOrder.objects.get(pk=int(context), status='open')
        except (ValueError, TypeError, CustomerOrder.DoesNotExist):
            messages.error(request, 'Selecciona un pedido activo o STOCK.')
            return redirect('production_board')
        unit = (OrderUnit.objects.select_related('physical_unit', 'order')
                .filter(order=selected_order, serial_number__iexact=sn).first())
        if unit is None:
            aiken_row = _aiken_exact(sn)
            vals = {f: _clean((aiken_row or {}).get(f)) for f in UNIT_FIELDS}
            physical, created = PhysicalUnit.objects.get_or_create(serial_number=sn, defaults=vals)
            if not created:
                physical_changed = []
                for f, value in vals.items():
                    if value and not _clean(getattr(physical, f, '')):
                        setattr(physical, f, value); physical_changed.append(f)
                if physical_changed:
                    physical.save(update_fields=physical_changed)
            defaults = {
                'serial_number': sn,
                'aiken_lot': _clean((aiken_row or {}).get('lot')) or selected_order.lot,
                **vals,
            }
            unit, _ = OrderUnit.objects.get_or_create(order=selected_order, physical_unit=physical, defaults=defaults)
            source_name = 'aiken' if aiken_row else 'manual'
            AuditLog.objects.create(
                user=request.user,
                action='board_unit_auto_added_to_order',
                object_type='OrderUnit', object_id=str(unit.pk),
                details={'serial_number': sn, 'order_id': selected_order.pk, 'order': selected_order.name,
                         'aiken_found': bool(aiken_row), 'source': source_name})
    else:
        unit = (OrderUnit.objects.select_related('physical_unit', 'order')
                .filter(serial_number__iexact=sn).order_by('-imported_at', '-pk').first())
        if unit is None:
            messages.error(request, f'{sn} no existe todavía en Almacén. Para dar una unidad nueva de alta selecciona el pedido al que pertenece.')
            return redirect('production_board')

    if unit:
        aiken_row = aiken_row or _aiken_exact(sn)
        if aiken_row:
            changed = []; physical_changed = []
            for f in UNIT_FIELDS:
                value = _clean(aiken_row.get(f))
                if value and not _clean(getattr(unit, f, '')):
                    setattr(unit, f, value); changed.append(f)
                if value and not _clean(getattr(unit.physical_unit, f, '')):
                    setattr(unit.physical_unit, f, value); physical_changed.append(f)
            if changed:
                unit.save(update_fields=changed)
            if physical_changed:
                unit.physical_unit.save(update_fields=physical_changed)

    with transaction.atomic():
        physical = PhysicalUnit.objects.select_for_update().get(pk=unit.physical_unit_id)
        now = timezone.now()

        membership = (PalletUnit.objects.select_for_update()
                      .select_related('pallet')
                      .filter(unit=unit).first())
        pallet_origin = None
        if membership:
            if membership.pallet.status == Pallet.STATUS_SHIPPED:
                messages.error(request, f'{sn} pertenece a {membership.pallet.code}, que ya fue enviado. La unidad está bloqueada y no puede extraerse.')
                return redirect('production_board')
            pallet_origin = {'pallet_id': membership.pallet_id, 'pallet_code': membership.pallet.code}
            AuditLog.objects.create(
                user=request.user,
                action='unit_extracted_from_pallet',
                object_type='PalletUnit',
                object_id=str(membership.pk),
                details={'serial_number': unit.serial_number, 'unit_id': unit.pk, 'order_id': unit.order_id,
                         'pallet_id': membership.pallet_id, 'pallet_code': membership.pallet.code,
                         'destination_zone_id': origin.pk, 'destination_zone': origin.name},
            )
            membership.delete()

        current = (PhysicalUnitLocation.objects.select_for_update().filter(physical_unit=physical)
                   .select_related('intervention', 'zone', 'worker').first())
        if current and current.zone_id == origin.pk:
            if current.worker_id == request.user.pk:
                messages.info(request, f'{sn} ya está en {origin.name} y continúa contando tiempo.')
            else:
                messages.error(request, f'{sn} ya está en {origin.name}, asignada a {current.worker.get_username()}.')
            return redirect('production_board')
        if current:
            _close(current.intervention, now, origin)
        for old in UnitIntervention.objects.select_for_update().filter(unit__physical_unit=physical, finished_at__isnull=True):
            _close(old, now, origin)
        missing = [f for f in UNIT_FIELDS if not _clean(getattr(unit, f, ''))]
        snapshot = {
            'serial_number': unit.serial_number, 'physical_unit_id': unit.physical_unit_id,
            'order_id': unit.order_id, 'order': unit.order.name,
            'brand': unit.brand, 'model': unit.model, 'processor': unit.processor,
            'ram': unit.ram, 'disk': unit.disk, 'aiken_lot': unit.aiken_lot,
            'work_context': 'order' if selected_order else 'stock',
            'selected_order_id': selected_order.pk if selected_order else None,
            'selected_order': selected_order.name if selected_order else 'STOCK',
            'aiken_found': bool(aiken_row), 'missing_fields': missing,
        }
        if pallet_origin:
            snapshot.update({'logistic_origin': 'pallet', **pallet_origin})
        intervention = UnitIntervention.objects.create(unit=unit, worker=request.user, zone=origin,
                                                       source=source_name, source_snapshot=snapshot)
        PhysicalUnitLocation.objects.update_or_create(
            physical_unit=physical,
            defaults={'unit': unit, 'zone': origin, 'intervention': intervention,
                      'worker': request.user, 'entered_at': now})
    if pallet_origin:
        messages.success(request, f'{sn} extraída de {pallet_origin["pallet_code"]} y añadida a {origin.name}.')
    elif missing:
        messages.warning(request, f'{sn} añadido. AIKEN no pudo completar: {", ".join(missing)}. Un administrador o gestor deberá cumplimentarlo.')
    else:
        messages.success(request, f'{sn} añadido a Mi Pizarra y ficha completada.')
    return redirect('production_board')


@login_required
@require_POST
def board_update_unit_field(request, unit_pk):
    if not _can_manual_edit(request.user):
        return HttpResponseForbidden('Sólo Administradores o Gestor pueden cumplimentar manualmente la ficha de una unidad.')
    unit = get_object_or_404(OrderUnit.objects.select_related('physical_unit'), pk=unit_pk)
    field = (request.POST.get('field') or '').strip()
    value = _clean(request.POST.get('value'))
    if field not in UNIT_FIELDS:
        return JsonResponse({'ok': False, 'error': 'Campo no permitido.'}, status=400)
    if not value:
        return JsonResponse({'ok': False, 'error': 'Indica un valor.'}, status=400)
    with transaction.atomic():
        setattr(unit, field, value); unit.save(update_fields=[field])
        physical = PhysicalUnit.objects.select_for_update().get(pk=unit.physical_unit_id)
        setattr(physical, field, value); physical.save(update_fields=[field])
        AuditLog.objects.create(user=request.user, action='board_unit_manual_field', object_type='OrderUnit',
                                object_id=str(unit.pk), details={'serial_number': unit.serial_number,
                                'field': field, 'value': value})
    return JsonResponse({'ok': True, 'field': field, 'value': value})
