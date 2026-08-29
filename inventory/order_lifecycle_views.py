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
 physical,_=PhysicalUnit.objects.get_or_create(serial_number=sn,defaults={'brand':str(row.get('brand') or order.brand),'model':str(row.get('model') or order.model),'processor':str(row.get('processor') or order.processor),'ram':str(row.get('ram') or order.ram),'disk':str(row.get('disk') or order.disk)})
 cycle,created=OrderUnit.objects.get_or_create(order=order,physical_unit=physical,defaults={'serial_number':sn,'aiken_lot':str(row.get('lot') or order.lot),'aiken_unit_id':str(row.get('id') or ''),'brand':str(row.get('brand') or physical.brand or order.brand),'model':str(row.get('model') or physical.model or order.model),'processor':str(row.get('processor') or physical.processor or order.processor),'ram':str(row.get('ram') or physical.ram or order.ram),'disk':str(row.get('disk') or physical.disk or order.disk)})
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
    sn=str(row.get('serial_number') or '').strip()
    if sn and _cycle(order,sn,row):created+=1
  messages.success(request,f'AIKEN: {created} ciclo(s) incorporado(s). Un SN histórico puede volver en un pedido posterior.')
 except Exception as exc:messages.error(request,f'No se pudo importar desde AIKEN: {exc}')
 return redirect('order_detail',pk=order.pk)