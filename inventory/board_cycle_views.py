from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import AuditLog, ProductionModelMySQLSource, ProductionZone
from .order_models import CustomerOrder, OrderUnit, PhysicalUnit
from .external_mysql import find_aiken_unit_exact
from .unit_workflow_models import UnitIntervention, PhysicalUnitLocation
from .pallet_models import Pallet, PalletUnit
from .permissions import user_is_warranty_manager

UNIT_FIELDS=('brand','model','processor','ram','disk')
def _clean(v):return ' '.join(str(v or '').strip().split())
def _can_work(u):return u.is_authenticated and not getattr(getattr(u,'inventory_profile',None),'is_guest',False)
def _stock():return CustomerOrder.objects.filter(name__iexact='stock',customer__isnull=True,status='open').order_by('pk').first()
def _warranty():return CustomerOrder.objects.filter(name__iexact='GARANTÍAS',customer__isnull=True,status='open').order_by('pk').first() or CustomerOrder.objects.filter(name__iexact='GARANTIAS',customer__isnull=True,status='open').order_by('pk').first()
def _is_warranty_order(order):return bool(order and order.name.strip().casefold() in ('garantías','garantias'))
def _is_warranty_zone(zone):return 'garant' in f'{zone.code} {zone.name}'.casefold()
def _aiken(sn):
 source=ProductionModelMySQLSource.objects.order_by('-updated_at').first()
 if not source:return None
 try:return find_aiken_unit_exact(source,sn)
 except Exception:return None
def _close(i,now,destination=None):
 if i.finished_at:return
 i.finished_at=now;i.duration_seconds=max(0,int((now-i.created_at).total_seconds()));i.destination_zone=destination;i.save(update_fields=['finished_at','duration_seconds','destination_zone'])
def _copy_cycle(previous,order):return OrderUnit.objects.create(order=order,physical_unit=previous.physical_unit,serial_number=previous.serial_number,aiken_lot=previous.aiken_lot or order.lot,aiken_unit_id=previous.aiken_unit_id,brand=previous.brand,model=previous.model,processor=previous.processor,ram=previous.ram,disk=previous.disk)

@login_required
@require_POST
def start_unit(request):
 if not _can_work(request.user):return HttpResponseForbidden('No tienes permiso para esta operación.')
 sn=(request.POST.get('serial_number') or '').strip();context=(request.POST.get('work_order') or 'stock').strip()
 if not sn:return redirect('production_board')
 origin=get_object_or_404(ProductionZone,pk=request.POST.get('origin_zone') or request.POST.get('zone'),is_active=True)
 order=_stock() if context=='stock' else None
 if context!='stock':
  try:order=CustomerOrder.objects.get(pk=int(context),status='open')
  except (TypeError,ValueError,CustomerOrder.DoesNotExist):messages.error(request,'Selecciona un pedido activo o STOCK.');return redirect('production_board')
 if order is None:messages.error(request,'No existe el pedido permanente STOCK.');return redirect('production_board')

 physical=PhysicalUnit.objects.filter(serial_number__iexact=sn).first()
 local_cycle=(OrderUnit.objects.select_related('order','physical_unit').filter(physical_unit=physical).order_by('-imported_at','-pk').first()) if physical else None
 has_warranty_history=bool(physical and OrderUnit.objects.filter(physical_unit=physical,order__name__iexact='GARANTÍAS').exists()) or bool(physical and OrderUnit.objects.filter(physical_unit=physical,order__name__iexact='GARANTIAS').exists())

 # Garantías es un circuito protegido. Un técnico normal sólo puede fichar en la
 # zona Garantías una unidad que ya pertenece al pedido GARANTÍAS. Responsable y
 # Gestor pueden incorporar cualquier SN (incluidas sustituciones o ciclos cerrados).
 if _is_warranty_zone(origin):
  warranty=_warranty()
  if warranty is None:messages.error(request,'No existe el pedido permanente GARANTÍAS. Ejecuta las migraciones.');return redirect('production_board')
  privileged=user_is_warranty_manager(request.user)
  current_is_warranty=bool(local_cycle and _is_warranty_order(local_cycle.order))
  if not current_is_warranty and not privileged:
   messages.error(request,'Sólo pueden entrar en Garantías unidades del pedido GARANTÍAS. El Responsable de Garantías o el Gestor pueden realizar una incorporación excepcional.')
   return redirect('production_board')
  # Entrar físicamente en Garantías siempre trabaja sobre el pedido permanente.
  # Si es una incorporación privilegiada se crea un nuevo ciclo conservando la procedencia.
  order=warranty;context=str(warranty.pk)

 row=None if (physical or local_cycle) else _aiken(sn);vals={f:_clean((row or {}).get(f)) for f in UNIT_FIELDS}
 with transaction.atomic():
  if physical is not None:physical=PhysicalUnit.objects.select_for_update().get(pk=physical.pk)
  else:physical=PhysicalUnit.objects.select_for_update().filter(serial_number__iexact=sn).first()
  if physical is None:physical=PhysicalUnit.objects.create(serial_number=sn,**vals)
  else:
   changed=[]
   for f,v in vals.items():
    if v and not _clean(getattr(physical,f,'')):setattr(physical,f,v);changed.append(f)
   if changed:physical.save(update_fields=changed)
  membership=(PalletUnit.objects.select_for_update().select_related('pallet','unit').filter(unit__physical_unit=physical).first());pallet_origin=None
  if membership:
   if membership.pallet.status==Pallet.STATUS_SHIPPED:messages.error(request,f'{sn} pertenece a {membership.pallet.code}, que ya fue enviado. No puede extraerse.');return redirect('production_board')
   pallet_origin={'pallet_id':membership.pallet_id,'pallet_code':membership.pallet.code,'membership_id':membership.pk};AuditLog.objects.create(user=request.user,action='unit_extracted_from_pallet',object_type='PalletUnit',object_id=str(membership.pk),details={'serial_number':sn,'pallet_id':membership.pallet_id,'pallet_code':membership.pallet.code,'destination_zone_id':origin.pk,'destination_zone':origin.name});membership.delete()
  current=OrderUnit.objects.select_for_update().filter(physical_unit=physical).select_related('order').order_by('-imported_at','-pk').first()
  if current is None:unit=OrderUnit.objects.create(order=order,physical_unit=physical,serial_number=sn,aiken_lot=_clean((row or {}).get('lot')) or order.lot,**vals);cycle_reason='warranty_intake' if _is_warranty_order(order) else 'first_intake'
  elif current.order_id==order.pk:unit=current;cycle_reason='warranty_return' if _is_warranty_order(order) else 'continue_cycle'
  else:
   unit=_copy_cycle(current,order);cycle_reason='warranty_intake' if _is_warranty_order(order) else ('returned_for_reconditioning' if order.name.casefold()=='stock' else 'assigned_to_order')
   AuditLog.objects.create(user=request.user,action='warranty_unit_admitted' if _is_warranty_order(order) else 'reconditioning_cycle_created',object_type='OrderUnit',object_id=str(unit.pk),details={'serial_number':sn,'previous_cycle_id':current.pk,'previous_order_id':current.order_id,'previous_order':current.order.name,'new_order_id':order.pk,'new_order':order.name,'reason':cycle_reason,'privileged_intake':bool(_is_warranty_order(order) and user_is_warranty_manager(request.user)),'had_warranty_history':has_warranty_history})
  changed=[]
  for f,v in vals.items():
   if v and not _clean(getattr(unit,f,'')):setattr(unit,f,v);changed.append(f)
  if changed:unit.save(update_fields=changed)
  now=timezone.now();location=PhysicalUnitLocation.objects.select_for_update().filter(physical_unit=physical).select_related('intervention','zone','worker').first()
  if location and location.zone_id==origin.pk and not location.intervention.finished_at:
   if location.worker_id==request.user.pk:messages.info(request,f'{sn} ya está en {origin.name} y continúa contando tiempo.')
   else:messages.error(request,f'{sn} ya está en {origin.name}, asignada a {location.worker.get_username()}.')
   return redirect('production_board')
  if location and not location.intervention.finished_at:_close(location.intervention,now,origin)
  for old in UnitIntervention.objects.select_for_update().filter(unit__physical_unit=physical,finished_at__isnull=True):_close(old,now,origin)
  snapshot={'serial_number':sn,'physical_unit_id':physical.pk,'order_id':order.pk,'order':order.name,'cycle_id':unit.pk,'cycle_reason':cycle_reason,'brand':unit.brand,'model':unit.model,'processor':unit.processor,'ram':unit.ram,'disk':unit.disk,'aiken_lot':unit.aiken_lot,'aiken_found':bool(row),'lookup_source':'local' if not row else 'aiken','work_context':'warranty' if _is_warranty_order(order) else ('stock' if context=='stock' else 'order'),'selected_order_id':None if context=='stock' else order.pk,'selected_order':'STOCK' if context=='stock' else order.name,'warranty_cycle':_is_warranty_order(order),'had_warranty_history':has_warranty_history}
  if pallet_origin:snapshot.update({'logistic_origin':'pallet',**pallet_origin})
  intervention=UnitIntervention.objects.create(unit=unit,worker=request.user,zone=origin,source='aiken' if row else ('manual' if cycle_reason in ('first_intake','warranty_intake') else 'local'),source_snapshot=snapshot)
  PhysicalUnitLocation.objects.update_or_create(physical_unit=physical,defaults={'unit':unit,'zone':origin,'intervention':intervention,'worker':request.user,'entered_at':now})
  AuditLog.objects.create(user=request.user,action='unit_picked_into_zone_stock',object_type='OrderUnit',object_id=str(unit.pk),details={'serial_number':sn,'zone_id':origin.pk,'zone':origin.name,'intervention_id':intervention.pk,'pallet_origin':pallet_origin,'lookup_source':'aiken' if row else 'local','warranty_cycle':_is_warranty_order(order)})
 if pallet_origin:messages.success(request,f'{sn} extraída de {pallet_origin["pallet_code"]} y fichada en {origin.name}.')
 else:messages.success(request,f'{sn} fichada en {origin.name} · ciclo actual: {order.name}.')
 return redirect('production_board')
