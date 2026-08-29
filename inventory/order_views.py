from decimal import Decimal, InvalidOperation
import io,re
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import get_user_model
from django.db import transaction, connection
from django.db.models import Q,Count
from django.http import HttpResponseForbidden, JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from openpyxl import Workbook
from .external_mysql import encrypt_password, list_aiken_lots, search_aiken_units, test_source
from .models import InventoryRecord, ProductionModelMySQLSource
from .order_models import BusinessRole,BusinessRoleAssignment,Customer,Supplier,CustomerOrder,OrderUnit,ComponentType,Component,Repair,ComponentReservation,RMA,ProcurementAlert,SavedQuery
from .permissions import PERMISSION_CHOICES,user_has_permission,user_is_purchasing

def _allowed(u,p): return u.is_staff or user_has_permission(u,p)
def _deny(): return HttpResponseForbidden('No tienes permiso para realizar esta operación.')
def _back(k): return redirect('internal_table',kind=k)
TABLES={'pedidos':(CustomerOrder,'Pedidos','orders.manage'),'clientes':(Customer,'Clientes','customers.manage'),'proveedores':(Supplier,'Proveedores','suppliers.manage'),'unidades':(OrderUnit,'Unidades','orders.manage'),'reparaciones':(Repair,'Reparaciones','repairs.manage'),'componentes':(Component,'Componentes','components.manage'),'reservas':(ComponentReservation,'Reservas de componentes','components.reserve'),'rma':(RMA,'RMA','rma.manage')}
def _rows(k):
 if k=='pedidos': return CustomerOrder.objects.select_related('customer').annotate(unit_count=Count('units')).order_by('-id')
 if k=='clientes': return Customer.objects.order_by('name')
 if k=='proveedores': return Supplier.objects.order_by('name')
 if k=='unidades': return OrderUnit.objects.select_related('order','order__customer').order_by('-id')
 if k=='reparaciones': return Repair.objects.select_related('unit','created_by','component_type').order_by('-id')
 if k=='componentes': return Component.objects.select_related('supplier','component_kind').order_by('-id')
 if k=='reservas': return ComponentReservation.objects.select_related('unit','repair','component','technician','installed_by').order_by('-id')
 return RMA.objects.select_related('component','component_type','supplier','unit','reservation').order_by('-id')
@login_required
def orders_center(request):
 if not _allowed(request.user,'orders.view'): return _deny()
 return render(request,'inventory/orders_center.html',{'concepts':[(k,v[1]) for k,v in TABLES.items()],'alerts':ProcurementAlert.objects.filter(status='open').order_by('-created_at') if user_is_purchasing(request.user) else ProcurementAlert.objects.none()})
@login_required
def internal_table(request,kind):
 if kind not in TABLES or not _allowed(request.user,'orders.view'): return _deny()
 _,title,perm=TABLES[kind]
 return render(request,'inventory/internal_table.html',{'kind':kind,'title':title,'objects':_rows(kind),'can_manage':_allowed(request.user,perm),'customers':Customer.objects.filter(active=True),'suppliers':Supplier.objects.filter(active=True),'orders':CustomerOrder.objects.order_by('-id'),'units':OrderUnit.objects.order_by('-id'),'component_types':ComponentType.objects.filter(active=True),'components':Component.objects.order_by('-id'),'inventory_records':InventoryRecord.objects.filter(status='available')[:1000]})
@login_required
def internal_detail(request,kind,pk):
 if kind=='pedidos': return render(request,'inventory/order_choice.html',{'order':get_object_or_404(CustomerOrder.objects.select_related('customer'),pk=pk)})
 if kind=='unidades': return redirect('unit_detail',pk=pk)
 if kind not in TABLES or not _allowed(request.user,'orders.view'): return _deny()
 obj=get_object_or_404(TABLES[kind][0],pk=pk); related=[]
 if kind=='clientes': related=obj.orders.all().order_by('-id')
 elif kind=='reparaciones': related=ComponentReservation.objects.filter(repair=obj)
 elif kind=='proveedores': related=Component.objects.filter(supplier=obj)
 elif kind=='componentes': related=obj.reservations.all()
 return render(request,'inventory/internal_detail.html',{'kind':kind,'title':TABLES[kind][1],'object':obj,'related':related})
@login_required
def order_detail(request,pk):
 if not _allowed(request.user,'orders.view'): return _deny()
 o=get_object_or_404(CustomerOrder.objects.select_related('customer'),pk=pk); units=o.units.all().order_by('serial_number'); rs=ComponentReservation.objects.filter(unit__order=o).select_related('component'); installed=rs.filter(status='installed'); cost=sum((x.component.price or Decimal('0')) for x in installed); source=_aiken_source(); aiken_ready=False; aiken_error=''
 if source:
  try: test_source(source); aiken_ready=True
  except Exception as exc: aiken_error=str(exc)
 return render(request,'inventory/order_detail.html',{'order':o,'units':units,'reservations':rs,'installed_count':installed.count(),'component_cost':cost,'can_manage':_allowed(request.user,'orders.manage'),'aiken_ready':aiken_ready,'aiken_error':aiken_error})
@login_required
def unit_detail(request,pk):
 if not _allowed(request.user,'orders.view'): return _deny()
 u=get_object_or_404(OrderUnit.objects.select_related('order','order__customer'),pk=pk)
 return render(request,'inventory/unit_detail.html',{'unit':u,'reservations':u.component_reservations.select_related('component','technician','installed_by','repair').order_by('-reserved_at'),'repairs':u.repairs.select_related('created_by').order_by('-created_at'),'available_components':Component.objects.filter(status='active').select_related('component_kind','supplier'),'can_reserve':_allowed(request.user,'components.reserve')})
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
 if request.method=='POST':
  o=CustomerOrder.objects.create(name=request.POST['name'].strip(),customer_id=request.POST['customer'],brand=request.POST.get('brand','').strip(),model=request.POST.get('model','').strip(),lot=request.POST.get('lot','').strip(),processor=request.POST.get('processor','').strip(),ram=request.POST.get('ram','').strip(),disk=request.POST.get('disk','').strip(),created_by=request.user); return redirect('order_detail',pk=o.pk)
 return _back('pedidos')
@login_required
def unit_create(request):
 if not _allowed(request.user,'orders.manage'): return _deny()
 if request.method=='POST':
  o=get_object_or_404(CustomerOrder,pk=request.POST['order']); u=OrderUnit.objects.create(order=o,serial_number=request.POST['serial_number'].strip(),aiken_lot=request.POST.get('aiken_lot','').strip() or o.lot,brand=o.brand,model=o.model,processor=o.processor,ram=o.ram,disk=o.disk); return redirect('unit_detail',pk=u.pk)
 return _back('unidades')
@login_required
def component_create(request):
 if not _allowed(request.user,'components.manage'): return _deny()
 if request.method=='POST':
  k=get_object_or_404(ComponentType,pk=request.POST['component_kind'],active=True)
  try: price=Decimal((request.POST.get('price') or '0').replace(',','.'))
  except InvalidOperation: price=Decimal('0')
  Component.objects.create(component_type=k.name,component_kind=k,supplier_id=request.POST.get('supplier') or None,reference=request.POST.get('reference','').strip(),price=price,observations=request.POST.get('observations','').strip()); messages.success(request,'Componente registrado.')
 return _back('componentes')
@login_required
def reserve_component(request,component_pk):
 if not _allowed(request.user,'components.reserve') or request.method!='POST': return _deny()
 with transaction.atomic():
  c=get_object_or_404(Component.objects.select_for_update(),pk=component_pk,status='active'); u=get_object_or_404(OrderUnit,pk=request.POST['unit']); ComponentReservation.objects.create(unit=u,component=c,technician=request.user,unit_serial_number=u.serial_number,observations=request.POST.get('observations','')); c.status='reserved'; c.save(update_fields=['status'])
 return redirect('unit_detail',pk=u.pk)
@login_required
def reservation_install(request,pk):
 r=get_object_or_404(ComponentReservation,pk=pk)
 if request.method!='POST' or not (_allowed(request.user,'repairs.manage') or _allowed(request.user,'components.reserve')): return _deny()
 if r.status=='active': r.install(request.user); messages.success(request,'Instalado; reparación creada.')
 return redirect('unit_detail',pk=r.unit_id)
@login_required
def reservation_cancel(request,pk):
 r=get_object_or_404(ComponentReservation,pk=pk)
 if request.method!='POST' or not (_allowed(request.user,'components.reserve') or r.technician_id==request.user.id): return _deny()
 if r.status=='active': r.cancel()
 return redirect('unit_detail',pk=r.unit_id)
@login_required
def component_low(request,pk):
 if not _allowed(request.user,'components.manage'): return _deny()
 if request.method=='POST': c=get_object_or_404(Component,pk=pk); c.status='low'; c.save(update_fields=['status'])
 return _back('componentes')
@login_required
def rma_create(request):
 if not _allowed(request.user,'rma.manage'): return _deny()
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
  elif action=='rename': item=get_object_or_404(ComponentType,pk=request.POST['id']); item.name=name or item.name; item.save(); Component.objects.filter(component_kind=item).update(component_type=item.name)
  elif action=='toggle': item=get_object_or_404(ComponentType,pk=request.POST['id']); item.active=not item.active; item.save(update_fields=['active'])
  return redirect('component_types_manager')
 return render(request,'inventory/component_types_manager.html',{'items':ComponentType.objects.order_by('name')})
@login_required
@user_passes_test(lambda u:u.is_superuser)
def aiken_settings(request):
 s=ProductionModelMySQLSource.objects.order_by('-updated_at').first()
 if request.method=='POST':
  candidate=ProductionModelMySQLSource(host=request.POST['host'].strip(),port=int(request.POST.get('port') or 3306),database=request.POST['database'].strip(),username=request.POST['username'].strip(),updated_by=request.user)
  password=request.POST.get('password','')
  if password: candidate.encrypted_password=encrypt_password(password)
  elif s: candidate.encrypted_password=s.encrypted_password
  try:
   test_source(candidate)
  except Exception as e:
   messages.error(request,f'CONEXIÓN AIKEN FALLIDA. No se ha guardado ningún cambio. Error: {e}')
   return render(request,'inventory/aiken_settings.html',{'source':candidate,'connection_status':'error','connection_message':f'No se pudo conectar con {candidate.host}:{candidate.port}/{candidate.database}. {e}'})
  if request.POST.get('action')=='test':
   messages.success(request,f'CONEXIÓN AIKEN CORRECTA. Servidor {candidate.host}:{candidate.port}, base {candidate.database}, usuario {candidate.username}. No se modificó la configuración guardada.')
   return render(request,'inventory/aiken_settings.html',{'source':candidate,'connection_status':'ok','connection_message':'Conexión comprobada correctamente. AIKEN responde y la tabla Units es accesible.'})
  if s is None: s=ProductionModelMySQLSource()
  s.host=candidate.host; s.port=candidate.port; s.database=candidate.database; s.username=candidate.username; s.encrypted_password=candidate.encrypted_password; s.updated_by=request.user; s.save()
  messages.success(request,f'CONEXIÓN AIKEN CORRECTA Y GUARDADA. {s.host}:{s.port} / {s.database} / usuario {s.username}.')
  return redirect('aiken_settings')
 status=''; msg=''
 if s:
  try: test_source(s); status='ok'; msg=f'Configuración activa comprobada: conexión correcta con {s.host}:{s.port}/{s.database}.'
  except Exception as e: status='error'; msg=f'La configuración guardada no conecta actualmente: {e}'
 return render(request,'inventory/aiken_settings.html',{'source':s,'connection_status':status,'connection_message':msg})
def _aiken_source(): return ProductionModelMySQLSource.objects.order_by('-updated_at').first()
@login_required
def aiken_sn_search(request):
 s=_aiken_source(); q=request.GET.get('q','').strip()
 if not s or not _allowed(request.user,'orders.manage'): return JsonResponse({'results':[]},status=400)
 try: return JsonResponse({'results':search_aiken_units(s,serial_query=q,limit=100) if q else []})
 except Exception as e: return JsonResponse({'error':str(e),'results':[]},status=400)
@login_required
def aiken_lot_search(request):
 s=_aiken_source()
 if not s or not _allowed(request.user,'orders.manage'): return JsonResponse({'results':[]},status=400)
 try: return JsonResponse({'results':list_aiken_lots(s,request.GET.get('q','').strip(),500)})
 except Exception as e: return JsonResponse({'error':str(e),'results':[]},status=400)
@login_required
def aiken_import(request,order_pk):
 if not _allowed(request.user,'orders.manage') or request.method!='POST': return _deny()
 o=get_object_or_404(CustomerOrder,pk=order_pk); s=_aiken_source(); rows=[]
 if not s: messages.error(request,'AIKEN no está configurado.'); return redirect('order_detail',pk=o.pk)
 try:
  test_source(s)
  if request.POST.get('mode')=='lot': rows=search_aiken_units(s,lot=request.POST.get('lot',''),limit=5000)
  else:
   for sn in request.POST.getlist('serial'): rows.extend(search_aiken_units(s,serial_query=sn.strip(),limit=20))
 except Exception as e: messages.error(request,f'No se pudo importar desde AIKEN: {e}'); return redirect('order_detail',pk=o.pk)
 created=0
 for row in rows:
  sn=str(row.get('serial_number') or '').strip()
  if sn and not OrderUnit.objects.filter(serial_number=sn).exists(): OrderUnit.objects.create(order=o,serial_number=sn,aiken_lot=str(row.get('lot') or o.lot),aiken_unit_id=str(row.get('id') or ''),brand=str(row.get('brand') or o.brand),model=str(row.get('model') or o.model),processor=str(row.get('processor') or o.processor),ram=str(row.get('ram') or o.ram),disk=str(row.get('disk') or o.disk)); created+=1
 messages.success(request,f'Importación AIKEN completada: {created} unidad(es) añadidas al pedido.'); return redirect('order_detail',pk=o.pk)

def _report_data(scope,pk):
 User=get_user_model()
 if scope=='pedido': subject=get_object_or_404(CustomerOrder.objects.select_related('customer'),pk=pk); title=f'Informe del pedido {subject.name}'; units=list(subject.units.all()); rs=list(ComponentReservation.objects.filter(unit__order=subject).select_related('unit','component','technician','installed_by','repair').order_by('unit__serial_number','reserved_at'))
 elif scope=='unidad': subject=get_object_or_404(OrderUnit,pk=pk); title=f'Informe de unidad {subject.serial_number}'; units=[subject]; rs=list(subject.component_reservations.select_related('unit','component','technician','installed_by','repair').order_by('reserved_at'))
 elif scope=='tecnico': subject=get_object_or_404(User,pk=pk); title=f'Informe del técnico {subject.get_username()}'; rs=list(ComponentReservation.objects.filter(Q(technician=subject)|Q(installed_by=subject)).select_related('unit','component','technician','installed_by','repair').distinct()); units=list({r.unit for r in rs if r.unit})
 else: return None
 repairs=[r.repair for r in rs if r.repair_id]; cost=sum((r.component.price or Decimal('0')) for r in rs if r.status=='installed'); return title,subject,units,rs,repairs,cost
@login_required
def report_view(request,scope,pk):
 if not _allowed(request.user,'orders.view'): return _deny()
 d=_report_data(scope,pk)
 if not d: return _deny()
 title,subject,units,rs,repairs,cost=d
 if request.GET.get('format')=='xlsx':
  wb=Workbook(); ws=wb.active; ws.title='Informe'; ws.append([title]); ws.append([]); ws.append(['SN','Reparación','Componente','Referencia','Precio','Reservó','Fecha reserva','Instaló','Fecha instalación','Estado'])
  for r in rs: ws.append([r.unit_serial_number,r.repair.repair_type if r.repair else '',r.component.component_type,r.component.reference,float(r.component.price or 0),r.technician.username,str(r.reserved_at),r.installed_by.username if r.installed_by else '',str(r.installed_at or ''),r.get_status_display()])
  ws.append([]); ws.append(['TOTAL INVERTIDO','','','',float(cost)]); out=io.BytesIO(); wb.save(out); resp=HttpResponse(out.getvalue(),content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'); resp['Content-Disposition']=f'attachment; filename="{slugify(title)}.xlsx"'; return resp
 return render(request,'inventory/trace_report.html',{'title':title,'scope':scope,'subject':subject,'units':units,'reservations':rs,'repairs':repairs,'component_cost':cost})
def _safe_sql(sql):
 s=re.sub(r'/\*.*?\*/',' ',sql,flags=re.S); s=re.sub(r'--.*?$',' ',s,flags=re.M).strip().rstrip(';').strip()
 return bool(re.match(r'^(select|with)\b',s,re.I)) and ';' not in s and not re.search(r'\b(insert|update|delete|drop|alter|create|replace|truncate|attach|detach|pragma|vacuum|grant|revoke|call|execute)\b',s,re.I)
def _execute_query(q):
 if not _safe_sql(q.sql): raise ValueError('Solo se permiten consultas de lectura SELECT/WITH de una sola sentencia.')
 with connection.cursor() as c: c.execute(q.sql); cols=[x[0] for x in c.description]; rows=c.fetchmany(10000)
 return cols,rows
@login_required
def query_center(request):
 if not _allowed(request.user,'orders.view'): return _deny()
 return render(request,'inventory/query_center.html',{'queries':SavedQuery.objects.filter(active=True).order_by('name'),'can_manage':request.user.is_superuser})
@login_required
def query_run(request,pk):
 if not _allowed(request.user,'orders.view'): return _deny()
 q=get_object_or_404(SavedQuery,pk=pk,active=True)
 try: cols,rows=_execute_query(q)
 except Exception as e: messages.error(request,f'Consulta no ejecutada: {e}'); return redirect('query_center')
 if request.GET.get('format')=='xlsx':
  wb=Workbook(); ws=wb.active; ws.title='Consulta'; ws.append(cols)
  for row in rows: ws.append([v if isinstance(v,(str,int,float,type(None))) else str(v) for v in row])
  out=io.BytesIO(); wb.save(out); resp=HttpResponse(out.getvalue(),content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'); resp['Content-Disposition']=f'attachment; filename="{slugify(q.name)}.xlsx"'; return resp
 return render(request,'inventory/query_result.html',{'query':q,'columns':cols,'rows':rows})
@login_required
@user_passes_test(lambda u:u.is_superuser)
def query_manage(request,pk=None):
 q=get_object_or_404(SavedQuery,pk=pk) if pk else None
 if request.method=='POST':
  sql=request.POST.get('sql','').strip()
  if not _safe_sql(sql): messages.error(request,'La sentencia debe ser SELECT/WITH de solo lectura y una sola sentencia.'); return redirect(request.path)
  if q is None: q=SavedQuery(created_by=request.user)
  q.name=request.POST['name'].strip(); q.description=request.POST.get('description','').strip(); q.sql=sql; q.active=request.POST.get('active')=='on'; q.save(); messages.success(request,'Consulta guardada.'); return redirect('query_center')
 return render(request,'inventory/query_edit.html',{'query':q})
@login_required
@user_passes_test(lambda u:u.is_superuser)
def roles_manager(request):
 U=get_user_model()
 if request.method=='POST':
  a=request.POST.get('action')
  if a=='create': n=request.POST['name'].strip(); BusinessRole.objects.create(name=n,code=slugify(n),permissions=[p for p,_ in PERMISSION_CHOICES if p in request.POST.getlist('permissions')])
  elif a=='update': r=get_object_or_404(BusinessRole,pk=request.POST['role']); r.permissions=[p for p,_ in PERMISSION_CHOICES if p in request.POST.getlist('permissions')]; r.active=request.POST.get('active')=='on'; r.save()
  elif a=='assign':
   u=get_object_or_404(U,pk=request.POST['user']); BusinessRoleAssignment.objects.filter(user=u).delete()
   for rid in request.POST.getlist('roles'): BusinessRoleAssignment.objects.create(user=u,role_id=rid)
  return redirect('roles_manager')
 return render(request,'inventory/roles_manager.html',{'roles':BusinessRole.objects.order_by('name'),'users':U.objects.filter(is_active=True).order_by('username'),'permission_choices':PERMISSION_CHOICES})
@login_required
@user_passes_test(lambda u:u.is_superuser)
def import_router(request):
 from . import views as v
 return v.import_view(request)
@login_required
@user_passes_test(lambda u:u.is_superuser)
def export_router(request):
 from . import views as v
 return v.export_view(request)
