from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect,render
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import ProductionEntry,ProductionModel,ProductionProcessor,ProductionZone,ProductionModelMySQLSource
from .order_models import Customer,Supplier,CustomerOrder,OrderUnit,PhysicalUnit,ComponentType,Component,Repair,ComponentReservation,RMA,ProcurementAlert,DevelopmentBatch
from .external_mysql import list_aiken_lots,search_aiken_units,test_source
DEV_PREFIX='DEV-'
def _is_developer(user):return bool(user.is_authenticated and (user.is_superuser or user.pulsia_role_assignments.filter(role__active=True,role__code='desarrollador').exists()))
def _deny():
 from django.http import HttpResponseForbidden
 return HttpResponseForbidden('Perfil Desarrollador requerido.')
def _delete_manifest(m):
 RMA.objects.filter(pk__in=m.get('rmas',[])).delete();ProcurementAlert.objects.filter(pk__in=m.get('alerts',[])).delete();ComponentReservation.objects.filter(pk__in=m.get('reservations',[])).delete();Repair.objects.filter(pk__in=m.get('repairs',[])).delete();ProductionEntry.objects.filter(pk__in=m.get('production_entries',[])).delete();OrderUnit.objects.filter(pk__in=m.get('units',[])).delete();CustomerOrder.objects.filter(pk__in=m.get('orders',[])).delete();Component.objects.filter(pk__in=m.get('components',[])).delete();PhysicalUnit.objects.filter(pk__in=m.get('physical_units',[]),order_cycles__isnull=True).delete();ProductionModel.objects.filter(pk__in=m.get('production_models',[]),entries__isnull=True).delete();ProductionProcessor.objects.filter(pk__in=m.get('production_processors',[]),entries__isnull=True).delete();ProductionZone.objects.filter(pk__in=m.get('production_zones',[]),unit_interventions__isnull=True).delete();Customer.objects.filter(pk__in=m.get('customers',[])).delete();Supplier.objects.filter(pk__in=m.get('suppliers',[])).delete()
def _aiken_rows():
 source=ProductionModelMySQLSource.objects.order_by('-updated_at').first()
 if not source:return [],'Lotes totalmente ficticios · AIKEN no configurado'
 try:
  test_source(source);lots=list_aiken_lots(source,'',20)
  for lot in lots[:10]:
   value=lot.get('lot') if isinstance(lot,dict) else lot
   if value not in (None,''):
    rows=search_aiken_units(source,lot=str(value),limit=10)
    if rows:return rows[:10],f'AIKEN · lote {value}'
  return [],'Lotes totalmente ficticios · AIKEN sin lote utilizable'
 except Exception:return [],'Lotes totalmente ficticios · AIKEN no disponible'
@login_required
def developer_center(request):
 if not _is_developer(request.user):return _deny()
 counts={'clientes':Customer.objects.filter(name__startswith=DEV_PREFIX).count(),'proveedores':Supplier.objects.filter(name__startswith=DEV_PREFIX).count(),'pedidos':CustomerOrder.objects.filter(name__startswith=DEV_PREFIX).count(),'unidades':OrderUnit.objects.filter(serial_number__startswith=DEV_PREFIX).count(),'componentes':Component.objects.filter(reference__startswith=DEV_PREFIX).count(),'reparaciones':Repair.objects.filter(observations__startswith=DEV_PREFIX).count(),'pizarra':ProductionEntry.objects.filter(model_name__startswith=DEV_PREFIX).count()}
 return render(request,'inventory/developer_center.html',{'counts':counts,'batches':DevelopmentBatch.objects.all()[:25]})
@login_required
@require_POST
def developer_seed(request):
 if not _is_developer(request.user):return _deny()
 token=timezone.now().strftime('%Y%m%d%H%M%S%f');manifest={k:[] for k in ['customers','suppliers','orders','units','physical_units','components','reservations','repairs','rmas','alerts','production_entries','production_zones','production_models','production_processors']}
 with transaction.atomic():
  customers=[];suppliers=[]
  for i in range(1,11):
   x=Customer.objects.create(name=f'{DEV_PREFIX}CLIENTE-{token}-{i:02d}',email=f'dev{i}-{token}@example.invalid',observations=f'{DEV_PREFIX}{token}');customers.append(x);manifest['customers'].append(x.pk);s=Supplier.objects.create(name=f'{DEV_PREFIX}PROVEEDOR-{token}-{i:02d}',email=f'prov{i}-{token}@example.invalid',observations=f'{DEV_PREFIX}{token}');suppliers.append(s);manifest['suppliers'].append(s.pk)
  kinds=[]
  for name in ['Pantalla','Batería','Teclado','Touchpad','SSD','RAM','Placa base','Ventilador','Altavoz','Webcam']:k,_=ComponentType.objects.get_or_create(name=name,defaults={'created_by':request.user});kinds.append(k)
  aiken,source_label=_aiken_rows();units=[]
  for i in range(10):
   o=CustomerOrder.objects.create(name=f'{DEV_PREFIX}PEDIDO-{token}-{i+1:02d}',customer=customers[i],brand='DELL' if i%2==0 else 'HP',model=f'MODELO-DEV-{i+1}',lot=f'{DEV_PREFIX}LOTE-{token}-{i+1:02d}',processor='Intel Core i5',ram='16 GB',disk='512 GB SSD',created_by=request.user);manifest['orders'].append(o.pk)
   for j in range(3):
    row=aiken[(i*3+j)%len(aiken)] if aiken else {};sn=f'{DEV_PREFIX}SN-{token}-{i+1:02d}-{j+1:02d}';p=PhysicalUnit.objects.create(serial_number=sn,brand=str(row.get('brand') or o.brand),model=str(row.get('model') or o.model),processor=str(row.get('processor') or o.processor),ram=str(row.get('ram') or o.ram),disk=str(row.get('disk') or o.disk));manifest['physical_units'].append(p.pk);u=OrderUnit.objects.create(order=o,physical_unit=p,serial_number=sn,aiken_lot=str(row.get('lot') or o.lot),aiken_unit_id=str(row.get('id') or ''),brand=p.brand,model=p.model,processor=p.processor,ram=p.ram,disk=p.disk);units.append(u);manifest['units'].append(u.pk)
  components=[]
  for i in range(60):k=kinds[i%len(kinds)];c=Component.objects.create(component_type=k.name,component_kind=k,supplier=suppliers[i%10],reference=f'{DEV_PREFIX}COMP-{token}-{i+1:03d}',price=Decimal(str(10+(i%20)*2.5)),observations=f'{DEV_PREFIX}{token}');components.append(c);manifest['components'].append(c.pk)
  for i,u in enumerate(units[:20]):c=components[i];r=ComponentReservation.objects.create(unit=u,component=c,technician=request.user,unit_serial_number=u.serial_number,observations=f'{DEV_PREFIX}{token}');manifest['reservations'].append(r.pk);c.status='reserved';c.save(update_fields=['status']);repair=r.install(request.user);manifest['repairs'].append(repair.pk)
  for i in range(20,25):c=components[i];c.status='low';c.save(update_fields=['status']);r=RMA.objects.create(component=c,component_type=c.component_kind,supplier=c.supplier,origin='supplier',reason=f'{DEV_PREFIX}{token} MERMA',created_by=request.user,observations=f'{DEV_PREFIX}{token}');manifest['rmas'].append(r.pk)
  for i,u in enumerate(units[20:25]):a=ProcurementAlert.objects.create(unit=u,component_type=kinds[i%len(kinds)],message=f'{DEV_PREFIX}{token} necesidad ficticia');manifest['alerts'].append(a.pk)
  zones=list(ProductionZone.objects.filter(is_active=True)[:5])
  if not zones:
   for code,name,pos in [('dev-auditoria','DEV Auditoría',900),('dev-reparacion','DEV Reparación',901)]:z=ProductionZone.objects.create(code=code,name=name,position=pos,created_by=request.user);zones.append(z);manifest['production_zones'].append(z.pk)
  pm,created=ProductionModel.objects.get_or_create(name=f'{DEV_PREFIX}MODELO-PRUEBA',defaults={'created_by':request.user});
  if created:manifest['production_models'].append(pm.pk)
  pp,created=ProductionProcessor.objects.get_or_create(name='Intel Core i5 DEV',defaults={'created_by':request.user});
  if created:manifest['production_processors'].append(pp.pk)
  for i in range(40):z=zones[i%len(zones)];dest=zones[(i+1)%len(zones)];e=ProductionEntry.objects.create(user=request.user,date=timezone.localdate(),hour=8+i%9,model_name=f'{DEV_PREFIX}{units[i%len(units)].serial_number}',production_model=pm,ram_gb=16,disk_gb=512,processor=pp,processor_name=pp.name,origin_zone=z.code,zone=dest.code,quantity=1);manifest['production_entries'].append(e.pk)
  DevelopmentBatch.objects.create(token=token,source=source_label,manifest=manifest,created_by=request.user)
 messages.success(request,f'Escenario DEV-{token} creado y reversible. {source_label}.');return redirect('developer_center')
@login_required
@require_POST
def developer_revert(request,pk):
 if not _is_developer(request.user):return _deny()
 with transaction.atomic():
  batch=DevelopmentBatch.objects.select_for_update().filter(pk=pk,status='active').first()
  if not batch:messages.error(request,'Ese escenario ya no está activo.');return redirect('developer_center')
  _delete_manifest(batch.manifest);batch.status='reverted';batch.reverted_by=request.user;batch.reverted_at=timezone.now();batch.save(update_fields=['status','reverted_by','reverted_at'])
 messages.success(request,f'Escenario DEV-{batch.token} revertido.');return redirect('developer_center')
@login_required
@require_POST
def developer_purge_orders(request):
 if not _is_developer(request.user):return _deny()
 if request.POST.get('confirm')!='VACIAR PEDIDOS':messages.error(request,'Confirmación incorrecta.');return redirect('developer_center')
 with transaction.atomic():
  for batch in DevelopmentBatch.objects.select_for_update().filter(status='active'):_delete_manifest(batch.manifest);batch.status='reverted';batch.reverted_by=request.user;batch.reverted_at=timezone.now();batch.save(update_fields=['status','reverted_by','reverted_at'])
  RMA.objects.all().delete();ProcurementAlert.objects.all().delete();ComponentReservation.objects.all().delete();Repair.objects.all().delete();OrderUnit.objects.all().delete();CustomerOrder.objects.all().delete();Component.objects.all().delete();Customer.objects.all().delete();Supplier.objects.all().delete();PhysicalUnit.objects.filter(order_cycles__isnull=True).delete()
 messages.warning(request,'Menú pedidos vaciado y escenarios DEV revertidos antes del vaciado.');return redirect('developer_center')
@login_required
@require_POST
def developer_purge_fake(request):
 if not _is_developer(request.user):return _deny()
 with transaction.atomic():
  for batch in DevelopmentBatch.objects.select_for_update().filter(status='active'):_delete_manifest(batch.manifest);batch.status='reverted';batch.reverted_by=request.user;batch.reverted_at=timezone.now();batch.save(update_fields=['status','reverted_by','reverted_at'])
 messages.success(request,'Todos los escenarios ficticios reversibles han sido retirados.');return redirect('developer_center')
