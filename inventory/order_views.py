from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify

from .external_mysql import encrypt_password, list_aiken_lots, search_aiken_units, test_source
from .models import InventoryRecord, ProductionModelMySQLSource
from .order_models import BusinessRole, BusinessRoleAssignment, Customer, Supplier, CustomerOrder, OrderUnit, ComponentType, Component, Repair, ComponentReservation, RMA, ProcurementAlert
from .permissions import PERMISSION_CHOICES, user_has_permission, user_is_purchasing


def _allowed(user,perm): return user.is_staff or user_has_permission(user,perm)
def _deny(): return HttpResponseForbidden('No tienes permiso para realizar esta operación.')
def _back(kind): return redirect('internal_table',kind=kind)

TABLES={
 'pedidos':(CustomerOrder,'Pedidos','orders.manage'), 'clientes':(Customer,'Clientes','customers.manage'),
 'proveedores':(Supplier,'Proveedores','suppliers.manage'), 'unidades':(OrderUnit,'Unidades','orders.manage'),
 'reparaciones':(Repair,'Reparaciones','repairs.manage'), 'componentes':(Component,'Componentes','components.manage'),
 'reservas':(ComponentReservation,'Reservas de componentes','components.reserve'), 'rma':(RMA,'RMA','rma.manage')}


def _rows(kind):
 if kind=='pedidos': return CustomerOrder.objects.select_related('customer').order_by('-id')
 if kind=='clientes': return Customer.objects.order_by('name')
 if kind=='proveedores': return Supplier.objects.order_by('name')
 if kind=='unidades': return OrderUnit.objects.select_related('order','order__customer').order_by('-id')
 if kind=='reparaciones': return Repair.objects.select_related('unit','created_by','component_type').order_by('-id')
 if kind=='componentes': return Component.objects.select_related('supplier','component_kind').order_by('-id')
 if kind=='reservas': return ComponentReservation.objects.select_related('unit','repair','component','technician','installed_by').order_by('-id')
 return RMA.objects.select_related('component','component_type','supplier','unit','reservation').order_by('-id')


@login_required
def orders_center(request):
 if not _allowed(request.user,'orders.view'): return _deny()
 return render(request,'inventory/orders_center.html',{
  'concepts':[(k,v[1]) for k,v in TABLES.items()],
  'alerts':ProcurementAlert.objects.filter(status='open').select_related('repair','unit','component_type').order_by('-created_at') if user_is_purchasing(request.user) else ProcurementAlert.objects.none(),
 })


@login_required
def internal_table(request,kind):
 if kind not in TABLES or not _allowed(request.user,'orders.view'): return _deny()
 model,title,manage_perm=TABLES[kind]
 return render(request,'inventory/internal_table.html',{
  'kind':kind,'title':title,'objects':_rows(kind),'can_manage':_allowed(request.user,manage_perm),
  'customers':Customer.objects.filter(active=True).order_by('name'),'suppliers':Supplier.objects.filter(active=True).order_by('name'),
  'orders':CustomerOrder.objects.order_by('-id'),'units':OrderUnit.objects.order_by('-id'),
  'component_types':ComponentType.objects.filter(active=True).order_by('name'),
  'components':Component.objects.select_related('supplier','component_kind').order_by('-id'),
  'inventory_records':InventoryRecord.objects.filter(status='available').select_related('table').order_by('table__name','internal_id')[:1000],
 })


@login_required
def internal_detail(request,kind,pk):
 if kind=='pedidos': return redirect('order_detail',pk=pk)
 if kind=='unidades': return redirect('unit_detail',pk=pk)
 if kind not in TABLES or not _allowed(request.user,'orders.view'): return _deny()
 obj=get_object_or_404(TABLES[kind][0],pk=pk); related=[]
 if kind=='clientes': related=obj.orders.all().order_by('-id')
 elif kind=='reparaciones': related=ComponentReservation.objects.filter(repair=obj).select_related('component','technician','installed_by')
 elif kind=='proveedores': related=Component.objects.filter(supplier=obj).order_by('-id')
 elif kind=='componentes': related=obj.reservations.select_related('unit','technician','installed_by').order_by('-id')
 return render(request,'inventory/internal_detail.html',{'kind':kind,'title':TABLES[kind][1],'object':obj,'related':related})


@login_required
def order_detail(request,pk):
 if not _allowed(request.user,'orders.view'): return _deny()
 order=get_object_or_404(CustomerOrder.objects.select_related('customer'),pk=pk)
 units=order.units.all().order_by('serial_number')
 reservations=ComponentReservation.objects.filter(unit__order=order).select_related('unit','component','technician','installed_by').order_by('-reserved_at')
 installed=reservations.filter(status='installed')
 cost=sum((r.component.price or Decimal('0')) for r in installed)
 return render(request,'inventory/order_detail.html',{'order':order,'units':units,'reservations':reservations,'installed_count':installed.count(),'component_cost':cost,'can_manage':_allowed(request.user,'orders.manage')})


@login_required
def unit_detail(request,pk):
 if not _allowed(request.user,'orders.view'): return _deny()
 unit=get_object_or_404(OrderUnit.objects.select_related('order','order__customer'),pk=pk)
 reservations=unit.component_reservations.select_related('component','component__component_kind','technician','installed_by','repair').order_by('-reserved_at')
 repairs=unit.repairs.select_related('created_by','component_type').order_by('-created_at')
 available=Component.objects.filter(status='active').select_related('component_kind','supplier').order_by('component_type','id')
 return render(request,'inventory/unit_detail.html',{'unit':unit,'reservations':reservations,'repairs':repairs,'available_components':available,'can_reserve':_allowed(request.user,'components.reserve')})


@login_required
def customer_create(request):
 if not _allowed(request.user,'customers.manage'): return _deny()
 if request.method=='POST':
  Customer.objects.create(name=request.POST['name'].strip(),phone=request.POST.get('phone','').strip(),email=request.POST.get('email','').strip(),address=request.POST.get('address','').strip(),delivery_point=request.POST.get('delivery_point','').strip(),contact=request.POST.get('contact','').strip(),observations=request.POST.get('observations','').strip()); messages.success(request,'Cliente creado.')
 return _back('clientes')

@login_required
def supplier_create(request):
 if not _allowed(request.user,'suppliers.manage'): return _deny()
 if request.method=='POST':
  Supplier.objects.create(name=request.POST['name'].strip(),phone=request.POST.get('phone','').strip(),email=request.POST.get('email','').strip(),address=request.POST.get('address','').strip(),delivery_point=request.POST.get('delivery_point','').strip(),contact=request.POST.get('contact','').strip(),observations=request.POST.get('observations','').strip()); messages.success(request,'Proveedor creado.')
 return _back('proveedores')

@login_required
def order_create(request):
 if not _allowed(request.user,'orders.manage'): return _deny()
 if request.method=='POST':
  obj=CustomerOrder.objects.create(name=request.POST['name'].strip(),customer_id=request.POST['customer'],brand=request.POST.get('brand','').strip(),model=request.POST.get('model','').strip(),lot=request.POST.get('lot','').strip(),processor=request.POST.get('processor','').strip(),ram=request.POST.get('ram','').strip(),disk=request.POST.get('disk','').strip(),created_by=request.user); messages.success(request,'Pedido creado.'); return redirect('order_detail',pk=obj.pk)
 return _back('pedidos')

@login_required
def unit_create(request):
 if not _allowed(request.user,'orders.manage'): return _deny()
 if request.method=='POST':
  order=get_object_or_404(CustomerOrder,pk=request.POST['order']); unit=OrderUnit.objects.create(order=order,serial_number=request.POST['serial_number'].strip(),aiken_lot=request.POST.get('aiken_lot','').strip() or order.lot,brand=request.POST.get('brand','').strip() or order.brand,model=request.POST.get('model','').strip() or order.model,processor=request.POST.get('processor','').strip() or order.processor,ram=request.POST.get('ram','').strip() or order.ram,disk=request.POST.get('disk','').strip() or order.disk); messages.success(request,'Unidad vinculada al pedido.'); return redirect('unit_detail',pk=unit.pk)
 return _back('unidades')

@login_required
def component_create(request):
 if not _allowed(request.user,'components.manage'): return _deny()
 if request.method=='POST':
  kind=get_object_or_404(ComponentType,pk=request.POST['component_kind'],active=True)
  try: price=Decimal((request.POST.get('price') or '0').replace(',','.'))
  except InvalidOperation: price=Decimal('0')
  Component.objects.create(component_type=kind.name,component_kind=kind,supplier_id=request.POST.get('supplier') or None,reference=request.POST.get('reference','').strip(),inventory_record_id=request.POST.get('inventory_record') or None,price=price,observations=request.POST.get('observations','').strip()); messages.success(request,'Componente registrado.')
 return _back('componentes')

@login_required
def reserve_component(request,component_pk):
 if not _allowed(request.user,'components.reserve') or request.method!='POST': return _deny()
 with transaction.atomic():
  component=get_object_or_404(Component.objects.select_for_update(),pk=component_pk,status='active')
  unit=get_object_or_404(OrderUnit,pk=request.POST['unit'])
  reservation=ComponentReservation.objects.create(unit=unit,component=component,technician=request.user,unit_serial_number=unit.serial_number,observations=request.POST.get('observations','').strip())
  component.status='reserved'; component.save(update_fields=['status'])
  if component.inventory_record_id:
   record=component.inventory_record; record.status='reserved'; record.current_sn=unit.serial_number; record.current_technician=request.user.get_username(); record.save(update_fields=['status','current_sn','current_technician','updated_at'])
  messages.success(request,f'Componente reservado para {unit.serial_number}.')
 return redirect(request.POST.get('next') or 'unit_detail',pk=unit.pk) if not request.POST.get('next') else redirect(request.POST['next'])

@login_required
def reservation_install(request,pk):
 r=get_object_or_404(ComponentReservation.objects.select_related('unit','component','component__component_kind'),pk=pk)
 if request.method!='POST' or not (_allowed(request.user,'repairs.manage') or _allowed(request.user,'components.reserve')): return _deny()
 if r.status!='active': messages.error(request,'Solo una reserva pendiente puede marcarse como instalada.')
 else:
  r.install(request.user); messages.success(request,'Componente marcado como instalado y reparación registrada automáticamente.')
 return redirect('unit_detail',pk=r.unit_id)

@login_required
def reservation_cancel(request,pk):
 r=get_object_or_404(ComponentReservation,pk=pk)
 if request.method!='POST' or not (_allowed(request.user,'components.reserve') or r.technician_id==request.user.id): return _deny()
 if r.status=='active': r.cancel(); messages.success(request,'Reserva cancelada y componente devuelto a disponible.')
 return redirect('unit_detail',pk=r.unit_id) if r.unit_id else _back('reservas')

@login_required
def component_low(request,pk):
 if not _allowed(request.user,'components.manage'): return _deny()
 c=get_object_or_404(Component,pk=pk)
 if request.method=='POST': c.status='low'; c.save(update_fields=['status']); messages.success(request,'Componente dado de baja.')
 return _back('componentes')

@login_required
def rma_create(request):
 if not _allowed(request.user,'rma.manage'): return _deny()
 if request.method=='POST':
  origin=request.POST.get('origin','supplier'); reservation=None; component=None; unit=None; supplier=None
  if request.POST.get('reservation'):
   reservation=get_object_or_404(ComponentReservation.objects.select_related('component','unit','component__supplier'),pk=request.POST['reservation']); component=reservation.component; unit=reservation.unit; supplier=component.supplier; component.status='low'; component.save(update_fields=['status']); origin='warehouse'
  elif request.POST.get('component'):
   component=get_object_or_404(Component,pk=request.POST['component']); component.status='low'; component.save(update_fields=['status']); supplier=component.supplier
  elif request.POST.get('unit'): unit=get_object_or_404(OrderUnit,pk=request.POST['unit'])
  kind=get_object_or_404(ComponentType,pk=request.POST['component_type']) if request.POST.get('component_type') else (component.component_kind if component else None)
  r=RMA(component=component,component_type=kind,unit=unit,reservation=reservation,supplier=supplier or (get_object_or_404(Supplier,pk=request.POST['supplier']) if request.POST.get('supplier') else None),origin=origin,reason=request.POST.get('reason','').strip(),observations=request.POST.get('observations','').strip(),created_by=request.user); r.full_clean(); r.save(); messages.success(request,'Baja/RMA registrada con su origen.')
 return _back('rma')

@login_required
def procurement_resolve(request,pk):
 a=get_object_or_404(ProcurementAlert,pk=pk)
 if request.method=='POST': a.status='resolved'; a.resolved_at=timezone.now(); a.save(update_fields=['status','resolved_at'])
 return redirect('orders_center')


@login_required
@user_passes_test(lambda u:u.is_superuser)
def component_types_manager(request):
 if request.method=='POST':
  action=request.POST.get('action'); name=request.POST.get('name','').strip()
  if action=='create' and name: ComponentType.objects.get_or_create(name=name,defaults={'created_by':request.user})
  elif action=='rename':
   item=get_object_or_404(ComponentType,pk=request.POST['id']); item.name=name or item.name; item.save(update_fields=['name'])
   Component.objects.filter(component_kind=item).update(component_type=item.name)
  elif action=='toggle':
   item=get_object_or_404(ComponentType,pk=request.POST['id']); item.active=not item.active; item.save(update_fields=['active'])
  return redirect('component_types_manager')
 return render(request,'inventory/component_types_manager.html',{'items':ComponentType.objects.order_by('name')})


@login_required
@user_passes_test(lambda u:u.is_superuser)
def aiken_settings(request):
 source=ProductionModelMySQLSource.objects.order_by('-updated_at').first()
 if request.method=='POST':
  if source is None: source=ProductionModelMySQLSource()
  source.host=request.POST['host'].strip(); source.port=int(request.POST.get('port') or 3306); source.database=request.POST['database'].strip(); source.username=request.POST['username'].strip(); source.updated_by=request.user
  if request.POST.get('password'): source.encrypted_password=encrypt_password(request.POST['password'])
  try:
   test_source(source)
  except Exception as exc:
   messages.error(request,f'No se pudo conectar con AIKEN: {exc}')
  else:
   source.save(); messages.success(request,'Conexión con AIKEN verificada y guardada de forma cifrada.'); return redirect('aiken_settings')
 return render(request,'inventory/aiken_settings.html',{'source':source})


def _aiken_source(): return ProductionModelMySQLSource.objects.order_by('-updated_at').first()

@login_required
def aiken_sn_search(request):
 if not _allowed(request.user,'orders.manage'): return _deny()
 source=_aiken_source(); q=request.GET.get('q','').strip()
 if not source: return JsonResponse({'error':'AIKEN no está configurado.','results':[]},status=400)
 if not q: return JsonResponse({'results':[]})
 try: rows=search_aiken_units(source,serial_query=q,limit=50)
 except Exception as exc: return JsonResponse({'error':str(exc),'results':[]},status=400)
 return JsonResponse({'results':rows})

@login_required
def aiken_lot_search(request):
 if not _allowed(request.user,'orders.manage'): return _deny()
 source=_aiken_source()
 if not source: return JsonResponse({'error':'AIKEN no está configurado.','results':[]},status=400)
 try: rows=list_aiken_lots(source,request.GET.get('q','').strip(),100)
 except Exception as exc: return JsonResponse({'error':str(exc),'results':[]},status=400)
 return JsonResponse({'results':rows})

@login_required
def aiken_import(request,order_pk):
 if not _allowed(request.user,'orders.manage') or request.method!='POST': return _deny()
 order=get_object_or_404(CustomerOrder,pk=order_pk); source=_aiken_source()
 if not source: messages.error(request,'Configure primero el servidor AIKEN.'); return redirect('order_detail',pk=order.pk)
 mode=request.POST.get('mode'); rows=[]
 try:
  if mode=='lot': rows=search_aiken_units(source,lot=request.POST.get('lot',''),limit=5000)
  else:
   serials=[s.strip() for s in request.POST.getlist('serial') if s.strip()]
   for sn in serials: rows.extend(search_aiken_units(source,serial_query=sn,limit=20))
 except Exception as exc:
  messages.error(request,f'Error consultando AIKEN: {exc}'); return redirect('order_detail',pk=order.pk)
 created=0; seen=set()
 for row in rows:
  sn=str(row.get('serial_number') or '').strip()
  if not sn or sn in seen: continue
  seen.add(sn)
  if OrderUnit.objects.filter(serial_number=sn).exists(): continue
  OrderUnit.objects.create(order=order,serial_number=sn,aiken_lot=str(row.get('lot') or order.lot or ''),aiken_unit_id=str(row.get('id') or ''),brand=str(row.get('brand') or order.brand or ''),model=str(row.get('model') or order.model or ''),processor=str(row.get('processor') or order.processor or ''),ram=str(row.get('ram') or order.ram or ''),disk=str(row.get('disk') or order.disk or '')); created+=1
 messages.success(request,f'{created} unidad(es) importadas desde AIKEN. Las ya vinculadas a otro pedido se han omitido.')
 return redirect('order_detail',pk=order.pk)


@login_required
def report_view(request,scope,pk):
 if not _allowed(request.user,'orders.view'): return _deny()
 User=get_user_model(); title=''; units=[]; reservations=[]
 if scope=='pedido':
  order=get_object_or_404(CustomerOrder.objects.select_related('customer'),pk=pk); title=f'Informe del pedido {order.name}'; units=list(order.units.all()); reservations=list(ComponentReservation.objects.filter(unit__order=order).select_related('unit','component','technician','installed_by','repair').order_by('reserved_at')); subject=order
 elif scope=='unidad':
  unit=get_object_or_404(OrderUnit.objects.select_related('order','order__customer'),pk=pk); title=f'Informe de unidad {unit.serial_number}'; units=[unit]; reservations=list(unit.component_reservations.select_related('component','technician','installed_by','repair').order_by('reserved_at')); subject=unit
 elif scope=='tecnico':
  tech=get_object_or_404(User,pk=pk); title=f'Informe del técnico {tech.get_username()}'; reservations=list(ComponentReservation.objects.filter(Q(technician=tech)|Q(installed_by=tech)).select_related('unit','unit__order','component','technician','installed_by','repair').distinct().order_by('reserved_at')); units=list({r.unit for r in reservations if r.unit}); subject=tech
 else: return _deny()
 repairs=[r.repair for r in reservations if r.repair_id]; cost=sum((r.component.price or Decimal('0')) for r in reservations if r.status=='installed')
 return render(request,'inventory/trace_report.html',{'title':title,'scope':scope,'subject':subject,'units':units,'reservations':reservations,'repairs':repairs,'component_cost':cost})


@login_required
@user_passes_test(lambda u:u.is_superuser)
def roles_manager(request):
 User=get_user_model()
 if request.method=='POST':
  action=request.POST.get('action')
  if action=='create': name=request.POST['name'].strip(); BusinessRole.objects.create(name=name,code=slugify(name),permissions=[p for p,_ in PERMISSION_CHOICES if p in request.POST.getlist('permissions')])
  elif action=='update': role=get_object_or_404(BusinessRole,pk=request.POST['role']); role.permissions=[p for p,_ in PERMISSION_CHOICES if p in request.POST.getlist('permissions')]; role.active=request.POST.get('active')=='on'; role.save()
  elif action=='assign':
   user=get_object_or_404(User,pk=request.POST['user']); BusinessRoleAssignment.objects.filter(user=user).delete()
   for rid in request.POST.getlist('roles'): BusinessRoleAssignment.objects.create(user=user,role_id=rid)
  return redirect('roles_manager')
 return render(request,'inventory/roles_manager.html',{'roles':BusinessRole.objects.order_by('name'),'users':User.objects.filter(is_active=True).order_by('username'),'permission_choices':PERMISSION_CHOICES})

@login_required
@user_passes_test(lambda u:u.is_superuser)
def import_router(request):
 from . import views as legacy_views
 return legacy_views.import_view(request)

@login_required
@user_passes_test(lambda u:u.is_superuser)
def export_router(request):
 from . import views as legacy_views
 return legacy_views.export_view(request)
