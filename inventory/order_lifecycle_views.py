from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404,redirect
from django.utils import timezone
from django.views.decorators.http import require_POST
from .order_models import CustomerOrder,OrderStatusEvent,OrderUnit,PhysicalUnit
from .models import ProductionModelMySQLSource
from .external_mysql import search_aiken_units,test_source
from .permissions import user_has_permission

def _allowed(u):return u.is_staff or user_has_permission(u,'orders.manage')
def _deny():
 from django.http import HttpResponseForbidden
 return HttpResponseForbidden('No tienes permiso para modificar el pedido.')
def _text(v):return ' '.join(str(v or '').strip().split())
def _values(order,row,physical=None):
 return {f:_text(row.get(f)) or _text(getattr(physical,f,'')) or _text(getattr(order,f,'')) for f in ('brand','model','processor','ram','disk')}
def _fill(obj,values):
 changed=[]
 for f,v in values.items():
  if not _text(getattr(obj,f,'')) and v:setattr(obj,f,v);changed.append(f)
 if changed:obj.save(update_fields=changed)
 return changed

@login_required
@require_POST
def set_order_status(request,pk,action):
 if not _allowed(request.user):return _deny()
 if action not in ('close','reopen'):return redirect('order_detail',pk=pk)
 with transaction.atomic():
  order=get_object_or_404(CustomerOrder.objects.select_for_update(),pk=pk)
  if action=='close' and order.status!='closed':order.status='closed';order.closed_at=timezone.now();order.closed_by=request.user;order.save(update_fields=['status','closed_at','closed_by']);OrderStatusEvent.objects.create(order=order,action='closed',user=request.user);messages.success(request,'Pedido cerrado. Su historial y unidades se conservan.')
  elif action=='reopen' and order.status!='open':order.status='open';order.closed_at=None;order.closed_by=None;order.save(update_fields=['status','closed_at','closed_by']);OrderStatusEvent.objects.create(order=order,action='reopened',user=request.user);messages.success(request,'Pedido reabierto.')
 return redirect('order_detail',pk=pk)

def _cycle(order,sn,row):
 initial=_values(order,row)
 physical,physical_created=PhysicalUnit.objects.get_or_create(serial_number=sn,defaults=initial)
 values=_values(order,row,physical)
 if not physical_created:_fill(physical,values)
 cycle,created=OrderUnit.objects.get_or_create(order=order,physical_unit=physical,defaults={'serial_number':sn,'aiken_lot':_text(row.get('lot')) or _text(order.lot),**values})
 if not created:
  _fill(cycle,values)
  if not _text(cycle.aiken_lot) and (_text(row.get('lot')) or _text(order.lot)):
   cycle.aiken_lot=_text(row.get('lot')) or _text(order.lot);cycle.save(update_fields=['aiken_lot'])
 return created

@login_required
@require_POST
def aiken_import_cycle(request,order_pk):
 if not _allowed(request.user):return _deny()
 order=get_object_or_404(CustomerOrder,pk=order_pk)
 if order.status!='open':messages.error(request,'Reabre el pedido antes de incorporar unidades.');return redirect('order_detail',pk=order.pk)
 source=ProductionModelMySQLSource.objects.order_by('-updated_at').first()
 if not source:messages.error(request,'AIKEN no está configurado.');return redirect('order_detail',pk=order.pk)
 try:
  test_source(source);rows=[]
  if request.POST.get('mode')=='lot':rows=search_aiken_units(source,lot=request.POST.get('lot',''),limit=5000)
  else:
   for sn in request.POST.getlist('serial'):rows.extend(search_aiken_units(source,serial_query=sn.strip(),limit=20))
  created=0
  with transaction.atomic():
   for row in rows:
    sn=_text(row.get('serial_number'))
    if sn and _cycle(order,sn,row):created+=1
  messages.success(request,f'AIKEN: {created} ciclo(s) nuevos. Los ciclos ya existentes también completan sus campos técnicos vacíos cuando AIKEN dispone del dato.')
 except Exception as exc:messages.error(request,f'No se pudo importar desde AIKEN: {exc}')
 return redirect('order_detail',pk=order.pk)