from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404,redirect
from django.utils import timezone
from django.views.decorators.http import require_POST
from .order_models import CustomerOrder,OrderStatusEvent
from .permissions import user_has_permission

def _allowed(u): return u.is_staff or user_has_permission(u,'orders.manage')

@login_required
@require_POST
def set_order_status(request,pk,action):
    if not _allowed(request.user):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden('No tienes permiso para modificar el pedido.')
    if action not in ('close','reopen'): return redirect('order_detail',pk=pk)
    with transaction.atomic():
        order=get_object_or_404(CustomerOrder.objects.select_for_update(),pk=pk)
        if action=='close' and order.status!='closed':
            order.status='closed';order.closed_at=timezone.now();order.closed_by=request.user;order.save(update_fields=['status','closed_at','closed_by']);OrderStatusEvent.objects.create(order=order,action='closed',user=request.user);messages.success(request,'Pedido cerrado. Su historial y unidades se conservan.')
        elif action=='reopen' and order.status!='open':
            order.status='open';order.closed_at=None;order.closed_by=None;order.save(update_fields=['status','closed_at','closed_by']);OrderStatusEvent.objects.create(order=order,action='reopened',user=request.user);messages.success(request,'Pedido reabierto.')
    return redirect('order_detail',pk=pk)