from decimal import Decimal, InvalidOperation
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models, transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST
from .component_flow_models import ComponentCatalog
from .models import InventoryField, InventoryRecord, InventoryTable, RecordMovement
from .order_models import Component, ComponentType
from .permissions import user_has_permission
COMMON_FIELDS=(('price','PRECIO','number'),('quantity','CANTIDAD','number'),('delivery_date','FECHA DE ENTREGA','date'),('reservation_date','FECHA DE RESERVA','date'),('technician','TÉCNICO','text'),('destination_sn','SN DE DESTINO','text'))
def _can_manage(user):return user.is_superuser or user.is_staff or user_has_permission(user,'components.manage')
def _deny():return HttpResponseForbidden('No tienes permiso para realizar esta operación.')
def _ensure_common_fields(table):
 position=table.inventory_fields.aggregate(m=models.Max('position'))['m'] or 0
 for key,name,field_type in COMMON_FIELDS:
  _,created=InventoryField.objects.get_or_create(table=table,key=key,defaults={'name':name,'position':position+1,'field_type':field_type,'is_destination_sn':key=='destination_sn','is_technician':key=='technician'})
  if created:position+=1
def _new_component_table(name,user):
 base=slugify(name) or 'componente';slug=f'componente-{base}';suffix=2
 while InventoryTable.objects.filter(slug=slug).exists():slug=f'componente-{base}-{suffix}';suffix+=1
 table=InventoryTable.objects.create(name=f'COMPONENTES · {name}',slug=slug,id_header='ID',id_prefix=f'{(base.upper().replace("-","")[:6] or "COMP")}-',id_width=5,next_number=1,created_by=user);InventoryField.objects.create(table=table,name='ID',key='id',position=0,field_type='text',is_primary=True);_ensure_common_fields(table);return table
@login_required
def component_catalog_index(request):
 catalogs=ComponentCatalog.objects.select_related('component_type','inventory_table').filter(active=True,component_type__active=True);return render(request,'inventory/component_catalog_index.html',{'catalogs':catalogs,'can_manage_components':_can_manage(request.user)})
@login_required
def component_catalog_manager(request):
 if not _can_manage(request.user):return _deny()
 if request.method=='POST':
  action=request.POST.get('action','')
  if action=='create_type':
   name=(request.POST.get('name') or '').strip()
   if name:
    with transaction.atomic():
     kind,_=ComponentType.objects.get_or_create(name=name,defaults={'created_by':request.user,'active':True});kind.active=True;kind.save(update_fields=['active'])
     try:kind.catalog
     except ComponentCatalog.DoesNotExist:ComponentCatalog.objects.create(component_type=kind,inventory_table=_new_component_table(name,request.user),created_by=request.user)
  elif action=='add_field':
   catalog=get_object_or_404(ComponentCatalog,pk=request.POST.get('catalog'));name=(request.POST.get('field_name') or '').strip();field_type=request.POST.get('field_type') or 'text'
   if name and field_type in {'text','number','date','bool'}:
    base=slugify(name).replace('-','_') or 'campo';key=base;n=2
    while catalog.inventory_table.inventory_fields.filter(key=key).exists():key=f'{base}_{n}';n+=1
    pos=(catalog.inventory_table.inventory_fields.aggregate(m=models.Max('position'))['m'] or 0)+1;InventoryField.objects.create(table=catalog.inventory_table,name=name.upper(),key=key,position=pos,field_type=field_type)
  elif action=='toggle':
   c=get_object_or_404(ComponentCatalog.objects.select_related('component_type','inventory_table'),pk=request.POST.get('catalog'));c.active=not c.active;c.component_type.active=c.active;c.inventory_table.active=c.active;c.save(update_fields=['active']);c.component_type.save(update_fields=['active']);c.inventory_table.save(update_fields=['active'])
  return redirect('component_catalog_manager')
 catalogs=ComponentCatalog.objects.select_related('component_type','inventory_table').prefetch_related('inventory_table__inventory_fields');return render(request,'inventory/component_catalog_manager.html',{'catalogs':catalogs})
@login_required
def component_catalog_table(request,catalog_pk):
 catalog=get_object_or_404(ComponentCatalog.objects.select_related('component_type','inventory_table'),pk=catalog_pk,active=True);table=catalog.inventory_table;_ensure_common_fields(table);fields=list(table.inventory_fields.all());records=table.records.all().order_by('internal_id')[:3000];rows=[{'record':r,'values':[r.internal_id if f.is_primary else (r.data or {}).get(f.key,'') for f in fields],'quantity':int((r.data or {}).get('quantity') or 0)} for r in records];return render(request,'inventory/component_catalog_table.html',{'catalog':catalog,'table':table,'fields':fields,'rows':rows,'can_manage_components':_can_manage(request.user)})
@login_required
@require_POST
def component_catalog_bulk_create(request,catalog_pk):
 if not _can_manage(request.user):return _deny()
 catalog=get_object_or_404(ComponentCatalog.objects.select_related('component_type','inventory_table'),pk=catalog_pk,active=True)
 try:quantity=max(1,int(request.POST.get('quantity') or 1))
 except ValueError:quantity=1
 try:price=Decimal((request.POST.get('price') or '0').replace(',','.'))
 except InvalidOperation:messages.error(request,'Precio no válido.');return redirect('component_catalog_table',catalog_pk=catalog.pk)
 if price<0:messages.error(request,'El precio no puede ser negativo.');return redirect('component_catalog_table',catalog_pk=catalog.pk)
 table=catalog.inventory_table;custom=list(table.inventory_fields.filter(is_primary=False).exclude(key__in=[x[0] for x in COMMON_FIELDS]));shared={f.key:(request.POST.get(f'field_{f.pk}') or '').strip() for f in custom};today=timezone.localdate().isoformat();data=dict(shared);data.update({'price':str(price),'quantity':str(quantity),'delivery_date':today,'reservation_date':'','technician':request.user.get_username(),'destination_sn':''})
 with transaction.atomic():
  locked=InventoryTable.objects.select_for_update().get(pk=table.pk);existing=None
  for r in InventoryRecord.objects.select_for_update().filter(table=locked):
   rd=r.data or {};same=all(str(rd.get(k,''))==str(v) for k,v in shared.items()) and str(rd.get('price',''))==str(price)
   if same:existing=r;break
  if existing:
   d=dict(existing.data or {});d['quantity']=str(int(d.get('quantity') or 0)+quantity);existing.data=d;existing.status='available';existing.save(update_fields=['data','status']);component=Component.objects.filter(inventory_record=existing).first()
   if component and component.status=='low':component.status='active';component.save(update_fields=['status'])
   RecordMovement.objects.create(record=existing,movement_type='entry',technician_name=request.user.get_username(),reason=f'Entrada acumulada +{quantity}',registered_by=request.user);messages.success(request,f'{quantity} unidad(es) sumadas a {existing.internal_id}. Cantidad total: {d["quantity"]}.')
  else:
   internal_id=f'{locked.id_prefix}{locked.next_number:0{locked.id_width}d}';locked.next_number+=1;locked.save(update_fields=['next_number']);record=InventoryRecord.objects.create(table=locked,internal_id=internal_id,data=data,status='available',created_by=request.user);Component.objects.create(component_type=catalog.component_type.name,component_kind=catalog.component_type,reference=internal_id,inventory_record=record,date=timezone.localdate(),price=price,status='active');RecordMovement.objects.create(record=record,movement_type='entry',technician_name=request.user.get_username(),reason=f'Alta lote componente x{quantity}',registered_by=request.user);messages.success(request,f'Lote {internal_id} creado con {quantity} unidad(es).')
 return redirect('component_catalog_table',catalog_pk=catalog.pk)
@login_required
@require_POST
def component_catalog_adjust_stock(request,catalog_pk,record_pk):
 if not _can_manage(request.user):return _deny()
 catalog=get_object_or_404(ComponentCatalog,pk=catalog_pk,active=True);record=get_object_or_404(InventoryRecord,pk=record_pk,table=catalog.inventory_table)
 try:delta=int(request.POST.get('delta') or 0)
 except ValueError:delta=0
 if not delta:messages.error(request,'Indica una cantidad distinta de cero.');return redirect('component_catalog_table',catalog_pk=catalog.pk)
 with transaction.atomic():
  record=InventoryRecord.objects.select_for_update().get(pk=record.pk);d=dict(record.data or {});current=int(d.get('quantity') or 0);new=current+delta
  if new<0:messages.error(request,f'No puedes retirar {abs(delta)}: solo hay {current} unidades.');return redirect('component_catalog_table',catalog_pk=catalog.pk)
  d['quantity']=str(new);record.data=d;record.status='available' if new>0 else 'reserved';record.save(update_fields=['data','status']);component=Component.objects.filter(inventory_record=record).first()
  if component:component.status='active' if new>0 else 'low';component.save(update_fields=['status'])
  RecordMovement.objects.create(record=record,movement_type='entry' if delta>0 else 'correction',technician_name=request.user.get_username(),reason=f'Ajuste manual de stock {delta:+d}',registered_by=request.user)
 messages.success(request,f'{record.internal_id}: cantidad actual {new}.');return redirect('component_catalog_table',catalog_pk=catalog.pk)
