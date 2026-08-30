from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models.deletion import ProtectedError, RestrictedError
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .order_models import (
    Customer,
    Supplier,
    CustomerOrder,
    OrderUnit,
    Repair,
    Component,
    ComponentReservation,
    RMA,
)
from .permissions import user_is_manager


TABLES = {
    "pedidos": (CustomerOrder, "Pedidos"),
    "clientes": (Customer, "Clientes"),
    "proveedores": (Supplier, "Proveedores"),
    "unidades": (OrderUnit, "Unidades"),
    "reparaciones": (Repair, "Reparaciones"),
    "componentes": (Component, "Componentes"),
    "reservas": (ComponentReservation, "Reservas de componentes"),
    "rma": (RMA, "RMA"),
}


def _deny():
    return HttpResponseForbidden("Solo el Gestor puede eliminar registros desde el Menú pedidos.")


@login_required
@require_POST
def internal_delete(request, kind, pk):
    if kind not in TABLES or not user_is_manager(request.user):
        return _deny()

    model, title = TABLES[kind]
    obj = get_object_or_404(model, pk=pk)
    label = str(obj)

    try:
        with transaction.atomic():
            obj.delete()
        messages.success(request, f'{title}: "{label}" eliminado.')
    except (ProtectedError, RestrictedError):
        messages.error(
            request,
            f'No se puede eliminar "{label}" porque tiene información relacionada que debe conservarse o eliminarse antes.',
        )
    except Exception as exc:
        messages.error(request, f'No se pudo eliminar "{label}": {exc}')

    return redirect("internal_table", kind=kind)
