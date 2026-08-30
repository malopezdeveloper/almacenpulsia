from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import AuditLog, ProductionZone
from .order_models import CustomerOrder, OrderUnit
from .priority_models import BoardPriority
from .permissions import user_has_permission


def _can_manage(user):
    return user.is_superuser or user.is_staff or user_has_permission(user, 'orders.manage')


def stock_order():
    return CustomerOrder.objects.filter(name__iexact='stock', customer__isnull=True).order_by('pk').first()


@login_required
def priority_check(request):
    """Indica si el SN/pedido es prioritario en la zona. Nunca bloquea el trabajo."""
    zone_id = (request.GET.get('zone') or '').strip()
    context = (request.GET.get('work_order') or 'stock').strip()
    sn = (request.GET.get('sn') or '').strip()
    applicable = BoardPriority.objects.filter(active=True).filter(models.Q(zone__isnull=True) | models.Q(zone_id=zone_id)).select_related('order', 'zone')
    if not applicable.exists():
        return JsonResponse({'has_priority': False, 'is_priority': True})
    order = None
    if context != 'stock':
        try: order = CustomerOrder.objects.filter(pk=int(context)).first()
        except (TypeError, ValueError): pass
    if order is None and sn:
        unit = OrderUnit.objects.filter(serial_number__iexact=sn).select_related('order').order_by('-imported_at', '-pk').first()
        order = unit.order if unit else None
    priority_orders = list(applicable.values_list('order_id', 'order__name'))
    is_priority = bool(order and any(pk == order.pk for pk, _ in priority_orders))
    names = ', '.join(dict.fromkeys(name for _, name in priority_orders))
    return JsonResponse({'has_priority': True, 'is_priority': is_priority, 'order': order.name if order else '', 'priority_orders': names, 'message': f'ATENCIÓN: esta unidad no es prioridad en esta zona. Prioridad actual: {names}. Puedes procesarla igualmente.' if not is_priority else ''})


@login_required
def priority_panel(request):
    if not _can_manage(request.user): return HttpResponseForbidden('Sólo Gestor y Administradores pueden gestionar prioridades.')
    if request.method == 'POST':
        order = get_object_or_404(CustomerOrder, pk=request.POST.get('order'), status='open')
        if order.name.casefold() == 'stock': messages.error(request, 'STOCK no puede establecerse como pedido prioritario.'); return redirect('board_priorities')
        zone_id = (request.POST.get('zone') or '').strip(); zone = get_object_or_404(ProductionZone, pk=zone_id, is_active=True) if zone_id else None
        priority, created = BoardPriority.objects.get_or_create(order=order, zone=zone, defaults={'created_by': request.user, 'active': True})
        if not created and not priority.active: priority.active = True; priority.created_by = request.user; priority.save(update_fields=['active', 'created_by'])
        AuditLog.objects.create(user=request.user, action='board_priority_enabled', object_type='CustomerOrder', object_id=str(order.pk), details={'order': order.name, 'zone': zone.name if zone else 'ALL'})
        messages.success(request, f'Prioridad activada: {order.name} · {zone.name if zone else "Todas las zonas"}.'); return redirect('board_priorities')
    priorities = BoardPriority.objects.filter(active=True).select_related('order', 'zone', 'created_by')
    orders = CustomerOrder.objects.filter(status='open').exclude(name__iexact='stock').select_related('customer').order_by('-pk')
    zones = ProductionZone.objects.filter(is_active=True).order_by('position', 'name')
    return render(request, 'inventory/board_priorities.html', {'priorities': priorities, 'orders': orders, 'zones': zones})


@login_required
@require_POST
def priority_disable(request, pk):
    if not _can_manage(request.user): return HttpResponseForbidden('Sólo Gestor y Administradores pueden gestionar prioridades.')
    priority = get_object_or_404(BoardPriority.objects.select_related('order', 'zone'), pk=pk); priority.active = False; priority.save(update_fields=['active'])
    AuditLog.objects.create(user=request.user, action='board_priority_disabled', object_type='CustomerOrder', object_id=str(priority.order_id), details={'order': priority.order.name, 'zone': priority.zone.name if priority.zone_id else 'ALL'})
    messages.success(request, 'Prioridad retirada.'); return redirect('board_priorities')


@login_required
@require_POST
def move_unit_to_stock(request, unit_pk):
    if not _can_manage(request.user): return HttpResponseForbidden('Sólo Gestor y Administradores pueden sacar unidades de un pedido.')
    unit = get_object_or_404(OrderUnit.objects.select_related('order', 'physical_unit'), pk=unit_pk); stock = stock_order()
    if stock is None: messages.error(request, 'No existe el pedido permanente STOCK. Ejecuta las migraciones de la actualización.'); return redirect('order_detail', pk=unit.order_id)
    if unit.order_id == stock.pk: messages.info(request, f'{unit.serial_number} ya pertenece a STOCK.'); return redirect('order_detail', pk=stock.pk)
    source_id = unit.order_id; source_name = unit.order.name
    try:
        with transaction.atomic():
            unit.order = stock; unit.save(update_fields=['order'])
            AuditLog.objects.create(user=request.user, action='order_unit_moved_to_stock', object_type='OrderUnit', object_id=str(unit.pk), details={'serial_number': unit.serial_number, 'from_order_id': source_id, 'from_order': source_name, 'to_order_id': stock.pk, 'to_order': 'STOCK'})
    except IntegrityError: messages.error(request, f'{unit.serial_number} ya tiene un ciclo en STOCK y no se puede duplicar.'); return redirect('order_detail', pk=source_id)
    messages.success(request, f'{unit.serial_number} retirada de {source_name} y enviada a STOCK.'); return redirect('order_detail', pk=source_id)


from django.db import models
