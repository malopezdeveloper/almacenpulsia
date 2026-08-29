from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from .models import InventoryRecord
from .order_models import BusinessRole,BusinessRoleAssignment,Customer,Supplier,CustomerOrder,OrderUnit,Component,Repair,ComponentReservation,RMA,ProcurementAlert
from .permissions import PERMISSION_CHOICES,user_has_permission,user_is_purchasing

def _allowed(user,perm): return user.is_staff or user_has_permission(user,perm)
def _deny(): return HttpResponseForbidden('No tienes permiso para realizar esta operación.')

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
 if kind=='reparaciones': return Repair.objects.select_related('unit','created_by').order_by('-id')
 if kind=='componentes': return Component.objects.select_related('supplier').order_by('-id')
 if kind=='reservas': return ComponentReservation.objects.select_related('repair','component','technician').order_by('-id')
 return RMA.objects.select_related('component','supplier').order_by('-id')

@login_required
def orders_center(request):
 if not _allowed(request.user,'orders.view'): return _deny()
 return render(request,'inventory/orders_center.html',{'concepts':[(k,v[1]) for k,v in TABLES.items()],'alerts':ProcurementAlert.objects.filter(status='open').select_related('repair','repair__unit').order_by('-created_at') if user_is_purchasing(request.user) else ProcurementAlert.objects.none()})

@login_required
def internal_table(request,kind):
 if kind not in TABLES: return _deny()
 model,title,manage_perm=TABLES[kind]
 if not _allowed(request.user,'orders.view'): return _deny()
 return render(request,'inventory/internal_table.html',{'kind':kind,'title':title,'objects':_rows(kind),'can_manage':_allowed(request.user,manage_perm),'customers':Customer.objects.filter(active=True).order_by('name'),'suppliers':Supplier.objects.filter(active=True).order_by('name'),'orders':CustomerOrder.objects.order_by('-id'),'units':OrderUnit.objects.order_by('-id'),'components':Component.objects.select_related('supplier').order_by('-id'),'inventory_records':InventoryRecord.objects.filter(status='available').select_related('table').order_by('table__name','internal_id')[:1000]})

@login_required
def internal_detail(request,kind,pk):
 if kind not in TABLES: return _deny()
 obj=get_object_or_404(TABLES[kind][0],pk=pk)
 related=[]
 if kind=='pedidos': related=obj.units.all().order_by('serial_number')
 elif kind=='clientes': related=obj.orders.all().order_by('-id')
 elif kind=='unidades': related=obj.repairs.all().order_by('-id')
 elif kind=='reparaciones': related=obj.component_reservations.all().order_by('-id') if hasattr(obj,'component_reservations') else ComponentReservation.objects.filter(repair=obj).order_by('-id')
 elif kind=='proveedores': related=Component.objects.filter(supplier=obj).order_by('-id')
 elif kind=='componentes': related=RMA.objects.filter(component=obj).order_by('-id')
 return render(request,'inventory/internal_detail.html',{'kind':kind,'title':TABLES[kind][1],'object':obj,'related':related})

def _back(kind): return redirect('internal_table',kind=kind)
@login_required
def customer_create(request):
 if not _allowed(request.user,'customers.manage'): return _deny()
 if request.method=='POST': Customer.objects.create(name=request.POST['name'].strip(),phone=request.POST.get('phone','').strip(),email=request.POST.get('email','').strip(),address=request.POST.get('address','').strip(),delivery_point=request.POST.get('delivery_point','').strip(),contact=request.POST.get('contact','').strip(),observations=request.POST.get('observations','').strip()); messages.success(request,'Cliente creado.')
 return _back('clientes')
@login_required
def supplier_create(request):
 if not _allowed(request.user,'suppliers.manage'): return _deny()
 if request.method=='POST': Supplier.objects.create(name=request.POST['name'].strip(),phone=request.POST.get('phone','').strip(),email=request.POST.get('email','').strip(),address=request.POST.get('address','').strip(),delivery_point=request.POST.get('delivery_point','').strip(),contact=request.POST.get('contact','').strip(),observations=request.POST.get('observations','').strip()); messages.success(request,'Proveedor creado.')
 return _back('proveedores')
@login_required
def order_create(request):
 if not _allowed(request.user,'orders.manage'): return _deny()
 if request.method=='POST': CustomerOrder.objects.create(name=request.POST['name'].strip(),customer_id=request.POST['customer'],brand=request.POST.get('brand','').strip(),model=request.POST.get('model','').strip(),lot=request.POST.get('lot','').strip(),processor=request.POST.get('processor','').strip(),ram=request.POST.get('ram','').strip(),disk=request.POST.get('disk','').strip(),created_by=request.user); messages.success(request,'Pedido creado.')
 return _back('pedidos')
@login_required
def unit_create(request):
 if not _allowed(request.user,'orders.manage'): return _deny()
 if request.method=='POST':
  order=get_object_or_404(CustomerOrder,pk=request.POST['order']); OrderUnit.objects.create(order=order,serial_number=request.POST['serial_number'].strip(),aiken_lot=request.POST.get('aiken_lot','').strip() or order.lot,brand=request.POST.get('brand','').strip() or order.brand,model=request.POST.get('model','').strip() or order.model,processor=request.POST.get('processor','').strip() or order.processor,ram=request.POST.get('ram','').strip() or order.ram,disk=request.POST.get('disk','').strip() or order.disk); messages.success(request,'Unidad vinculada al pedido.')
 return _back('unidades')
@login_required
def component_create(request):
 if not _allowed(request.user,'components.manage'): return _deny()
 if request.method=='POST': Component.objects.create(component_type=request.POST['component_type'].strip(),supplier_id=request.POST.get('supplier') or None,reference=request.POST.get('reference','').strip(),inventory_record_id=request.POST.get('inventory_record') or None,observations=request.POST.get('observations','').strip()); messages.success(request,'Componente registrado.')
 return _back('componentes')
@login_required
def repair_create(request):
 if not _allowed(request.user,'repairs.manage'): return _deny()
 if request.method!='POST': return _back('reparaciones')
 with transaction.atomic():
  unit=get_object_or_404(OrderUnit,pk=request.POST['unit']); repair_type=request.POST['repair_type'].strip(); repair=Repair.objects.create(unit=unit,repair_type=repair_type,observations=request.POST.get('observations','').strip(),created_by=request.user); component=Component.objects.select_for_update().filter(component_type__iexact=repair_type,status='active').order_by('id').first()
  if component: ComponentReservation.objects.create(repair=repair,component=component,technician=request.user,unit_serial_number=unit.serial_number); component.status='reserved'; component.save(update_fields=['status']); messages.success(request,'Reparación creada y componente reservado.')
  else: ProcurementAlert.objects.create(repair=repair,message=f'Falta componente {repair_type} para la unidad {unit.serial_number}.'); messages.error(request,'ALERTA DE COMPRAS: no existe componente compatible disponible.')
 return _back('reparaciones')
@login_required
def reservation_cancel(request,pk):
 r=get_object_or_404(ComponentReservation,pk=pk)
 if request.method!='POST' or not (_allowed(request.user,'components.reserve') or r.technician_id==request.user.id): return _deny()
 if r.status=='active': r.cancel(); messages.success(request,'Reserva cancelada.')
 return _back('reservas')
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
  c=get_object_or_404(Component,pk=request.POST['component'],status='low')
  if c.supplier_id: r=RMA(component=c,supplier=c.supplier,reason=request.POST.get('reason','').strip(),observations=request.POST.get('observations','').strip(),created_by=request.user); r.full_clean(); r.save(); messages.success(request,'RMA creado.')
 return _back('rma')
@login_required
def procurement_resolve(request,pk):
 a=get_object_or_404(ProcurementAlert,pk=pk)
 if request.method=='POST': a.status='resolved'; a.resolved_at=timezone.now(); a.save(update_fields=['status','resolved_at'])
 return redirect('orders_center')

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

# Se conservan los enrutadores de importación/exportación existentes mediante las vistas históricas.
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
