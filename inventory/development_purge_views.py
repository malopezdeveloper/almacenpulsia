from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .models import InventoryTable
from .order_models import (
    Customer, Supplier, CustomerOrder, OrderUnit, PhysicalUnit, Component,
    Repair, ComponentReservation, RMA, ProcurementAlert,
)
from .permissions import user_is_manager
from .unit_workflow_models import UnitIntervention, PhysicalUnitLocation


def _deny():
    return HttpResponseForbidden('Esta herramienta temporal de desarrollo es exclusiva del Gestor.')


def _purge_reservations(qs=None):
    qs = qs if qs is not None else ComponentReservation.objects.all()
    ids = list(qs.values_list('pk', flat=True))
    if not ids:
        return 0
    RMA.objects.filter(reservation_id__in=ids).delete()
    # ReservationInstallation se elimina por CASCADE con la reserva.
    count = len(ids)
    ComponentReservation.objects.filter(pk__in=ids).delete()
    return count


def _purge_repairs(qs=None):
    qs = qs if qs is not None else Repair.objects.all()
    ids = list(qs.values_list('pk', flat=True))
    if not ids:
        return 0
    _purge_reservations(ComponentReservation.objects.filter(repair_id__in=ids))
    ProcurementAlert.objects.filter(repair_id__in=ids).delete()
    count = len(ids)
    Repair.objects.filter(pk__in=ids).delete()
    return count


def _purge_units(qs=None):
    qs = qs if qs is not None else OrderUnit.objects.all()
    ids = list(qs.values_list('pk', flat=True))
    if not ids:
        return 0
    RMA.objects.filter(unit_id__in=ids).delete()
    _purge_reservations(ComponentReservation.objects.filter(unit_id__in=ids))
    _purge_repairs(Repair.objects.filter(unit_id__in=ids))
    ProcurementAlert.objects.filter(unit_id__in=ids).delete()
    PhysicalUnitLocation.objects.filter(unit_id__in=ids).delete()
    UnitIntervention.objects.filter(unit_id__in=ids).delete()
    physical_ids = list(OrderUnit.objects.filter(pk__in=ids).values_list('physical_unit_id', flat=True))
    count = len(ids)
    OrderUnit.objects.filter(pk__in=ids).delete()
    PhysicalUnit.objects.filter(pk__in=physical_ids, order_cycles__isnull=True).delete()
    return count


def _purge_components(qs=None):
    qs = qs if qs is not None else Component.objects.all()
    ids = list(qs.values_list('pk', flat=True))
    if not ids:
        return 0
    RMA.objects.filter(component_id__in=ids).delete()
    _purge_reservations(ComponentReservation.objects.filter(component_id__in=ids))
    count = len(ids)
    Component.objects.filter(pk__in=ids).delete()
    return count


@login_required
@require_POST
def purge_order_table(request, kind):
    if not user_is_manager(request.user):
        return _deny()
    labels = {
        'pedidos': 'Pedidos', 'clientes': 'Clientes', 'proveedores': 'Proveedores',
        'unidades': 'Unidades', 'componentes': 'Componentes', 'reservas': 'Reservas',
        'reparaciones': 'Reparaciones', 'rma': 'RMA',
    }
    if kind not in labels:
        messages.error(request, 'Tabla de desarrollo no reconocida.')
        return redirect('developer_center')
    if request.POST.get('confirm') != f'PURGAR {kind.upper()}':
        messages.error(request, f'Escribe exactamente PURGAR {kind.upper()} para confirmar.')
        return redirect('internal_table', kind=kind)
    with transaction.atomic():
        if kind == 'reservas': count = _purge_reservations()
        elif kind == 'reparaciones': count = _purge_repairs()
        elif kind == 'rma': count = RMA.objects.count(); RMA.objects.all().delete()
        elif kind == 'unidades': count = _purge_units()
        elif kind == 'componentes': count = _purge_components()
        elif kind == 'pedidos':
            count = CustomerOrder.objects.count()
            _purge_units(OrderUnit.objects.all())
            CustomerOrder.objects.all().delete()
        elif kind == 'clientes':
            count = Customer.objects.count()
            _purge_units(OrderUnit.objects.filter(order__customer__isnull=False))
            CustomerOrder.objects.all().delete()
            Customer.objects.all().delete()
        else:  # proveedores
            count = Supplier.objects.count()
            _purge_components(Component.objects.filter(supplier__isnull=False))
            RMA.objects.filter(supplier__isnull=False).delete()
            Supplier.objects.all().delete()
    messages.warning(request, f'DESARROLLO: tabla {labels[kind]} purgada ({count} registros principales).')
    return redirect('internal_table', kind=kind)


@login_required
@require_POST
def purge_inventory_table(request, slug):
    if not user_is_manager(request.user):
        return _deny()
    table = get_object_or_404(InventoryTable, slug=slug)
    if request.POST.get('confirm') != 'PURGAR TABLA':
        messages.error(request, 'Escribe exactamente PURGAR TABLA para confirmar.')
        return redirect('developer_center')
    records = table.records.all()
    record_ids = list(records.values_list('pk', flat=True))
    components = Component.objects.filter(inventory_record_id__in=record_ids)
    with transaction.atomic():
        _purge_components(components)
        count = len(record_ids)
        records.delete()
    messages.warning(request, f'DESARROLLO: inventario {table.name} purgado ({count} filas). La estructura de la tabla se conserva.')
    return redirect('developer_center')
