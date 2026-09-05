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

UNIT_FIELDS=('brand','model','processor','ram','disk')
def _clean(v):return ' '.join(str(v or '').strip().split())
def _can_work(u):return u.is_authenticated and not getattr(getattr(u,'inventory_profile',None),'is_guest',False)
def _stock():return CustomerOrder.objects.filter(name__iexact='stock',customer__isnull=True,status='open').order_by('pk').first()
def _aiken(sn):
 source=ProductionModelMySQLSource.objects.order_by('-updated_at').first()
 if not source:return None
 try:return find_aiken_unit_exact(source,sn)
 except Exception:return None
def _close(i,now,destination=None):
 if i.finished_at:return
 i.finished_at=now;i.duration_seconds=max(0,int((now-i.created_at).total_seconds()));i.destination_zone=destination;i.save(update_fields=['finished_at','duration_seconds','destination_zone'])
def _copy_cycle(previous,order):
 return OrderUnit.objects.create(order=order,physical_unit=previous.physical_unit,serial_number=previous.serial_number,aiken_lot=previous.aiken_lot or order.lot,aiken_unit_id=previous.aiken_unit_id,brand=previous.brand,model=previous.model,processor=previous.processor,ram=previous.ram,disk=previous.disk)

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
 row=_aiken(sn);vals={f:_clean((row or {}).get(f)) for f in UNIT_FIELDS}
 with transaction.atomic():
  physical=PhysicalUnit.objects.select_for_update().filter(serial_number__iexact=sn).first()
  if physical is None:physical=PhysicalUnit.objects.create(serial_number=sn,**vals)
  else:
   changed=[]
   for f,v in vals.items():
    if v and not _clean(getattr(physical,f,'')):setattr(physical,f,v);changed.append(f)
   if changed:physical.save(update_fields=changed)

  # Un palet abierto es stock logístico extraíble por cualquier zona. Un palet
  # enviado queda bloqueado definitivamente para el flujo de producción.
  membership=(PalletUnit.objects.select_for_update().select_related('pallet','unit')
              .filter(unit__physical_unit=physical).first())
  pallet_origin=None
  if membership:
   if membership.pallet.status==Pallet.STATUS_SHIPPED:
    messages.error(request,f'{sn} pertenece a {membership.pallet.code}, que ya fue enviado. No puede extraerse.')
    return redirect('production_board')
   pallet_origin={'pallet_id':membership.pallet_id,'pallet_code':membership.pallet.code,'membership_id':membership.pk}
   AuditLog.objects.create(user=request.user,action='unit_extracted_from_pallet',object_type='PalletUnit',object_id=str(membership.pk),details={'serial_number':sn,'pallet_id':membership.pallet_id,'pallet_code':membership.pallet.code,'destination_zone_id':origin.pk,'destination_zone':origin.name})
   membership.delete()

  current=OrderUnit.objects.select_for_update().filter(physical_unit=physical).select_related('order').order_by('-imported_at','-pk').first()
  if current is None:
   unit=OrderUnit.objects.create(order=order,physical_unit=physical,serial_number=sn,aiken_lot=_clean((row or {}).get('lot')) or order.lot,**vals);cycle_reason='first_intake'
  elif current.order_id==order.pk:
   unit=current;cycle_reason='continue_cycle'
  else:
   unit=_copy_cycle(current,order);cycle_reason='returned_for_reconditioning' if order.name.casefold()=='stock' else 'assigned_to_order'
   AuditLog.objects.create(user=request.user,action='reconditioning_cycle_created',object_type='OrderUnit',object_id=str(unit.pk),details={'serial_number':sn,'previous_cycle_id':current.pk,'previous_order_id':current.order_id,'new_order_id':order.pk,'new_order':order.name,'reason':cycle_reason})
  changed=[]
  for f,v in vals.items():
   if v and not _clean(getattr(unit,f,'')):setattr(unit,f,v);changed.append(f)
  if changed:unit.save(update_fields=changed)

  now=timezone.now();location=PhysicalUnitLocation.objects.select_for_update().filter(physical_unit=physical).select_related('intervention','zone','worker').first()
  if location and location.zone_id==origin.pk and not location.intervention.finished_at:
   if location.worker_id==request.user.pk:messages.info(request,f'{sn} ya está en {origin.name} y continúa contando tiempo.')
   else:messages.error(request,f'{sn} ya está en {origin.name}, asignada a {location.worker.get_username()}.')
   return redirect('production_board')

  # Fichar una unidad es lo que cambia su stock físico de zona. Si estaba en
  # stock terminado de esa misma zona, simplemente comienza una nueva intervención.
  if location and not location.intervention.finished_at:_close(location.intervention,now,origin)
  for old in UnitIntervention.objects.select_for_update().filter(unit__physical_unit=physical,finished_at__isnull=True):_close(old,now,origin)
  snapshot={'serial_number':sn,'physical_unit_id':physical.pk,'order_id':order.pk,'order':order.name,'cycle_id':unit.pk,'cycle_reason':cycle_reason,'brand':unit.brand,'model':unit.model,'processor':unit.processor,'ram':unit.ram,'disk':unit.disk,'aiken_lot':unit.aiken_lot,'aiken_found':bool(row),'work_context':'stock' if context=='stock' else 'order','selected_order_id':None if context=='stock' else order.pk,'selected_order':'STOCK' if context=='stock' else order.name}
  if pallet_origin:snapshot.update({'logistic_origin':'pallet',**pallet_origin})
  intervention=UnitIntervention.objects.create(unit=unit,worker=request.user,zone=origin,source='aiken' if row else ('manual' if cycle_reason=='first_intake' else 'local'),source_snapshot=snapshot)
  PhysicalUnitLocation.objects.update_or_create(physical_unit=physical,defaults={'unit':unit,'zone':origin,'intervention':intervention,'worker':request.user,'entered_at':now})
  AuditLog.objects.create(user=request.user,action='unit_picked_into_zone_stock',object_type='OrderUnit',object_id=str(unit.pk),details={'serial_number':sn,'zone_id':origin.pk,'zone':origin.name,'intervention_id':intervention.pk,'pallet_origin':pallet_origin})
 if pallet_origin:messages.success(request,f'{sn} extraída de {pallet_origin["pallet_code"]} y fichada en {origin.name}.')
 else:messages.success(request,f'{sn} fichada en {origin.name} · ciclo actual: {order.name}.')
 return redirect('production_board')
