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


COMMON_FIELDS = (
    ('price', 'PRECIO', 'number'),
    ('delivery_date', 'FECHA DE ENTREGA', 'date'),
    ('reservation_date', 'FECHA DE RESERVA', 'date'),
    ('technician', 'TÉCNICO', 'text'),
    ('destination_sn', 'SN DE DESTINO', 'text'),
)


def _can_manage(user):
    return user.is_superuser or user.is_staff or user_has_permission(user, 'components.manage')


def _deny():
    return HttpResponseForbidden('No tienes permiso para realizar esta operación.')


def _ensure_common_fields(table):
    position = table.inventory_fields.aggregate(models_max=models.Max('position'))['models_max'] or 0
    for key, name, field_type in COMMON_FIELDS:
        field, created = InventoryField.objects.get_or_create(
            table=table,
            key=key,
            defaults={
                'name': name,
                'position': position + 1,
                'field_type': field_type,
                'is_destination_sn': key == 'destination_sn',
                'is_technician': key == 'technician',
            },
        )
        if created:
            position += 1


def _new_component_table(name, user):
    base = slugify(name) or 'componente'
    slug = f'componente-{base}'
    suffix = 2
    while InventoryTable.objects.filter(slug=slug).exists():
        slug = f'componente-{base}-{suffix}'
        suffix += 1
    table = InventoryTable.objects.create(
        name=f'COMPONENTES · {name}', slug=slug, id_header='ID',
        id_prefix=f'{(base.upper().replace("-", "")[:6] or "COMP")}-',
        id_width=5, next_number=1, created_by=user,
    )
    InventoryField.objects.create(table=table, name='ID', key='id', position=0, field_type='text', is_primary=True)
    _ensure_common_fields(table)
    return table


@login_required
def component_catalog_index(request):
    catalogs = ComponentCatalog.objects.select_related('component_type', 'inventory_table').filter(active=True, component_type__active=True)
    return render(request, 'inventory/component_catalog_index.html', {'catalogs': catalogs, 'can_manage_components': _can_manage(request.user)})


@login_required
def component_catalog_manager(request):
    if not _can_manage(request.user): return _deny()
    if request.method == 'POST':
        action = request.POST.get('action', '')
        if action == 'create_type':
            name = (request.POST.get('name') or '').strip()
            if name:
                with transaction.atomic():
                    kind, _ = ComponentType.objects.get_or_create(name=name, defaults={'created_by': request.user, 'active': True})
                    kind.active = True; kind.save(update_fields=['active'])
                    try: kind.catalog
                    except ComponentCatalog.DoesNotExist:
                        table = _new_component_table(name, request.user)
                        ComponentCatalog.objects.create(component_type=kind, inventory_table=table, created_by=request.user)
                messages.success(request, f'Tipo {name} creado con su propia tabla y formulario.')
        elif action == 'add_field':
            catalog = get_object_or_404(ComponentCatalog, pk=request.POST.get('catalog'))
            name = (request.POST.get('field_name') or '').strip(); field_type = request.POST.get('field_type') or 'text'
            if name and field_type in {'text','number','date','bool'}:
                key_base = slugify(name).replace('-', '_') or 'campo'; key = key_base; n = 2
                while catalog.inventory_table.inventory_fields.filter(key=key).exists(): key=f'{key_base}_{n}'; n+=1
                pos = (catalog.inventory_table.inventory_fields.aggregate(m=models.Max('position'))['m'] or 0) + 1
                InventoryField.objects.create(table=catalog.inventory_table, name=name.upper(), key=key, position=pos, field_type=field_type)
                messages.success(request, 'Campo añadido al formulario del componente.')
        elif action == 'toggle':
            catalog = get_object_or_404(ComponentCatalog.objects.select_related('component_type', 'inventory_table'), pk=request.POST.get('catalog'))
            catalog.active = not catalog.active; catalog.component_type.active = catalog.active; catalog.inventory_table.active = catalog.active
            catalog.save(update_fields=['active']); catalog.component_type.save(update_fields=['active']); catalog.inventory_table.save(update_fields=['active'])
        return redirect('component_catalog_manager')
    catalogs = ComponentCatalog.objects.select_related('component_type', 'inventory_table').prefetch_related('inventory_table__inventory_fields')
    return render(request, 'inventory/component_catalog_manager.html', {'catalogs': catalogs})


@login_required
def component_catalog_table(request, catalog_pk):
    catalog = get_object_or_404(ComponentCatalog.objects.select_related('component_type', 'inventory_table'), pk=catalog_pk, active=True)
    table = catalog.inventory_table; fields = list(table.inventory_fields.all()); records = table.records.all().order_by('internal_id')[:3000]
    rows = [{'record':r,'values':[r.internal_id if f.is_primary else (r.data or {}).get(f.key,'') for f in fields]} for r in records]
    return render(request, 'inventory/component_catalog_table.html', {'catalog':catalog,'table':table,'fields':fields,'rows':rows,'can_manage_components':_can_manage(request.user)})


@login_required
@require_POST
def component_catalog_bulk_create(request, catalog_pk):
    if not _can_manage(request.user): return _deny()
    catalog = get_object_or_404(ComponentCatalog.objects.select_related('component_type','inventory_table'), pk=catalog_pk, active=True)
    try: quantity=max(1,min(int(request.POST.get('quantity') or 1),1000))
    except ValueError: quantity=1
    try: price=Decimal((request.POST.get('price') or '0').replace(',','.'))
    except InvalidOperation:
        messages.error(request,'Precio no válido.'); return redirect('component_catalog_table',catalog_pk=catalog.pk)
    if price<0: messages.error(request,'El precio no puede ser negativo.'); return redirect('component_catalog_table',catalog_pk=catalog.pk)
    table=catalog.inventory_table; custom_fields=list(table.inventory_fields.filter(is_primary=False).exclude(key__in=[x[0] for x in COMMON_FIELDS])); shared={f.key:(request.POST.get(f'field_{f.pk}') or '').strip() for f in custom_fields}; today=timezone.localdate().isoformat(); created=[]
    with transaction.atomic():
        locked=InventoryTable.objects.select_for_update().get(pk=table.pk)
        for _ in range(quantity):
            internal_id=f'{locked.id_prefix}{locked.next_number:0{locked.id_width}d}'; locked.next_number+=1; data=dict(shared); data.update({'price':str(price),'delivery_date':today,'reservation_date':'','technician':request.user.get_username(),'destination_sn':''})
            record=InventoryRecord.objects.create(table=locked,internal_id=internal_id,data=data,status='available',created_by=request.user)
            Component.objects.create(component_type=catalog.component_type.name,component_kind=catalog.component_type,reference=internal_id,inventory_record=record,date=timezone.localdate(),price=price,status='active')
            RecordMovement.objects.create(record=record,movement_type='entry',technician_name=request.user.get_username(),reason='Alta de componente',registered_by=request.user); created.append(internal_id)
        locked.save(update_fields=['next_number'])
    messages.success(request,f'{len(created)} componente(s) creados. IDs: {created[0]} → {created[-1]}.'); return redirect('component_catalog_table',catalog_pk=catalog.pk)
