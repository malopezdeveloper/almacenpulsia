import random
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import ProductionEntry,ProductionModel,ProductionProcessor,ProductionZone
from .order_models import BusinessRoleAssignment,Customer,Supplier,CustomerOrder,OrderUnit,ComponentType,Component,Repair,ComponentReservation,RMA,ProcurementAlert
from .external_mysql import list_aiken_lots,search_aiken_units,test_source
from .models import ProductionModelMySQLSource

DEV_PREFIX='DEV-'

def _is_developer(user):
    return bool(user.is_authenticated and (user.is_superuser or user.pulsia_role_assignments.filter(role__active=True,role__code='desarrollador').exists()))

def _guard(request):
    return _is_developer(request.user)

@login_required
def developer_center(request):
    if not _guard(request):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden('Perfil Desarrollador requerido.')
    counts={'clientes':Customer.objects.filter(name__startswith=DEV_PREFIX).count(),'proveedores':Supplier.objects.filter(name__startswith=DEV_PREFIX).count(),'pedidos':CustomerOrder.objects.filter(name__startswith=DEV_PREFIX).count(),'unidades':OrderUnit.objects.filter(serial_number__startswith=DEV_PREFIX).count(),'componentes':Component.objects.filter(reference__startswith=DEV_PREFIX).count(),'reparaciones':Repair.objects.filter(observations__startswith=DEV_PREFIX).count(),'pizarra':ProductionEntry.objects.filter(model_name__startswith=DEV_PREFIX).count()}
    return render(request,'inventory/developer_center.html',{'counts':counts})

def _aiken_rows():
    source=ProductionModelMySQLSource.objects.order_by('-updated_at').first()
    if not source: return [],'AIKEN no configurado'
    try:
        test_source(source); lots=list_aiken_lots(source,'',20)
        rows=[]
        for lot in lots[:10]:
            value=lot.get('lot') if isinstance(lot,dict) else lot
            if value not in (None,''):
                rows=search_aiken_units(source,lot=str(value),limit=10)
                if rows: return rows[:10],f'AIKEN · lote {value}'
        return [],'AIKEN conectado, sin lote utilizable'
    except Exception as exc: return [],f'AIKEN no disponible: {exc}'

@login_required
@require_POST
def developer_seed(request):
    if not _guard(request):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden('Perfil Desarrollador requerido.')
    token=timezone.now().strftime('%Y%m%d%H%M%S')
    with transaction.atomic():
        customers=[Customer.objects.create(name=f'{DEV_PREFIX}CLIENTE-{token}-{i:02d}',email=f'dev{i}@example.invalid',observations=f'{DEV_PREFIX} DATO FICTICIO') for i in range(1,11)]
        suppliers=[Supplier.objects.create(name=f'{DEV_PREFIX}PROVEEDOR-{token}-{i:02d}',email=f'proveedor{i}@example.invalid',observations=f'{DEV_PREFIX} DATO FICTICIO') for i in range(1,11)]
        kinds=[]
        for name in ['Pantalla','Batería','Teclado','Touchpad','SSD','RAM','Placa base','Ventilador','Altavoz','Webcam']:
            k,_=ComponentType.objects.get_or_create(name=name,defaults={'created_by':request.user}); kinds.append(k)
        aiken,source_label=_aiken_rows()
        orders=[]; units=[]
        for i in range(10):
            order=CustomerOrder.objects.create(name=f'{DEV_PREFIX}PEDIDO-{token}-{i+1:02d}',customer=customers[i],brand='DELL' if i%2==0 else 'HP',model=f'MODELO-DEV-{i+1}',lot=f'{DEV_PREFIX}LOTE-{token}-{i+1:02d}',processor='Intel Core i5',ram='16 GB',disk='512 GB SSD',created_by=request.user); orders.append(order)
            for j in range(3):
                row=aiken[(i*3+j)%len(aiken)] if aiken else {}
                # Se usa AIKEN como fuente de atributos, pero SN de prueba aislado para no contaminar datos reales.
                sn=f'{DEV_PREFIX}SN-{token}-{i+1:02d}-{j+1:02d}'
                u=OrderUnit.objects.create(order=order,serial_number=sn,aiken_lot=str(row.get('lot') or order.lot),aiken_unit_id=str(row.get('id') or ''),brand=str(row.get('brand') or order.brand),model=str(row.get('model') or order.model),processor=str(row.get('processor') or order.processor),ram=str(row.get('ram') or order.ram),disk=str(row.get('disk') or order.disk)); units.append(u)
        components=[]
        for i in range(60):
            k=kinds[i%len(kinds)]; components.append(Component.objects.create(component_type=k.name,component_kind=k,supplier=suppliers[i%10],reference=f'{DEV_PREFIX}COMP-{token}-{i+1:03d}',price=Decimal(str(10+(i%20)*2.5)),observations=f'{DEV_PREFIX} DATO FICTICIO'))
        # Reservas, instalaciones/reparaciones y algunas bajas/RMA.
        for i,u in enumerate(units[:20]):
            c=components[i]; r=ComponentReservation.objects.create(unit=u,component=c,technician=request.user,unit_serial_number=u.serial_number,observations=f'{DEV_PREFIX} REPARACION FICTICIA'); c.status='reserved'; c.save(update_fields=['status']); r.install(request.user)
        for i in range(20,25):
            c=components[i]; c.status='low'; c.save(update_fields=['status']); RMA.objects.create(component=c,component_type=c.component_kind,supplier=c.supplier,origin='supplier',reason=f'{DEV_PREFIX} MERMA FICTICIA',created_by=request.user,observations=f'{DEV_PREFIX} RMA FICTICIO')
        for i,u in enumerate(units[20:25]):
            ProcurementAlert.objects.create(unit=u,component_type=kinds[i%len(kinds)],message=f'{DEV_PREFIX} Necesidad ficticia de {kinds[i%len(kinds)].name}')
        zones=list(ProductionZone.objects.filter(is_active=True)[:5])
        if not zones:
            zones=[ProductionZone.objects.create(code='dev-auditoria',name='DEV Auditoría',position=900,created_by=request.user),ProductionZone.objects.create(code='dev-reparacion',name='DEV Reparación',position=901,created_by=request.user)]
        pm,_=ProductionModel.objects.get_or_create(name=f'{DEV_PREFIX}MODELO-PRUEBA',defaults={'created_by':request.user})
        pp,_=ProductionProcessor.objects.get_or_create(name='Intel Core i5 DEV',defaults={'created_by':request.user})
        for i in range(40):
            z=zones[i%len(zones)]; dest=zones[(i+1)%len(zones)]
            ProductionEntry.objects.create(user=request.user,date=timezone.localdate(),hour=(8+i%9),model_name=f'{DEV_PREFIX}{units[i%len(units)].serial_number}',production_model=pm,ram_gb=16,disk_gb=512,processor=pp,processor_name=pp.name,origin_zone=z.code,zone=dest.code,quantity=1)
    messages.success(request,f'Datos de desarrollo creados: 10 clientes, 10 proveedores, 10 pedidos, 30 unidades, componentes, reparaciones, RMA/mermas, alertas y 40 movimientos de Pizarra. Fuente de unidades: {source_label}.')
    return redirect('developer_center')

@login_required
@require_POST
def developer_purge_orders(request):
    if not _guard(request):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden('Perfil Desarrollador requerido.')
    if request.POST.get('confirm')!='VACIAR PEDIDOS':
        messages.error(request,'Confirmación incorrecta. No se ha eliminado nada.'); return redirect('developer_center')
    with transaction.atomic():
        # El vaciado afecta al dominio Pedidos; no toca inventario general, usuarios, configuración, AIKEN ni backups.
        RMA.objects.all().delete(); ProcurementAlert.objects.all().delete(); ComponentReservation.objects.all().delete(); Repair.objects.all().delete(); OrderUnit.objects.all().delete(); CustomerOrder.objects.all().delete()
    messages.warning(request,'Tablas operativas de Pedidos vaciadas. Clientes, proveedores y stock de componentes se han conservado.')
    return redirect('developer_center')

@login_required
@require_POST
def developer_purge_fake(request):
    if not _guard(request):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden('Perfil Desarrollador requerido.')
    with transaction.atomic():
        RMA.objects.filter(observations__startswith=DEV_PREFIX).delete(); ProcurementAlert.objects.filter(message__startswith=DEV_PREFIX).delete(); ComponentReservation.objects.filter(observations__startswith=DEV_PREFIX).delete(); Repair.objects.filter(observations__startswith=DEV_PREFIX).delete(); OrderUnit.objects.filter(serial_number__startswith=DEV_PREFIX).delete(); CustomerOrder.objects.filter(name__startswith=DEV_PREFIX).delete(); Component.objects.filter(reference__startswith=DEV_PREFIX).delete(); Customer.objects.filter(name__startswith=DEV_PREFIX).delete(); Supplier.objects.filter(name__startswith=DEV_PREFIX).delete(); ProductionEntry.objects.filter(model_name__startswith=DEV_PREFIX).delete()
    messages.success(request,'Datos ficticios DEV eliminados sin tocar datos reales.')
    return redirect('developer_center')