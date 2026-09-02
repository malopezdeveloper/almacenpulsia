from django.db import migrations
from django.utils.text import slugify

COMMON_FIELDS = (
    ('price', 'PRECIO', 'number'),
    ('quantity', 'CANTIDAD', 'number'),
    ('delivery_date', 'FECHA DE ENTREGA', 'date'),
    ('reservation_date', 'FECHA DE RESERVA', 'date'),
    ('technician', 'TÉCNICO', 'text'),
    ('destination_sn', 'SN DE DESTINO', 'text'),
)


def sync_catalogs(apps, schema_editor):
    ComponentType = apps.get_model('inventory', 'ComponentType')
    ComponentCatalog = apps.get_model('inventory', 'ComponentCatalog')
    InventoryTable = apps.get_model('inventory', 'InventoryTable')
    InventoryField = apps.get_model('inventory', 'InventoryField')
    User = apps.get_model('auth', 'User')

    fallback = User.objects.filter(is_active=True, is_superuser=True).order_by('pk').first() or User.objects.filter(is_active=True).order_by('pk').first()
    if fallback is None:
        return

    # Solo las tablas reales del inventario son plantillas. Las tablas de
    # componentes ya generadas se excluyen para evitar recursión/duplicados.
    source_tables = list(InventoryTable.objects.filter(active=True).exclude(slug__startswith='componente-').order_by('position', 'pk'))

    for source in source_tables:
        kind, _ = ComponentType.objects.get_or_create(
            name=source.name,
            defaults={'active': True, 'created_by_id': fallback.pk},
        )
        changed = []
        if not kind.active:
            kind.active = True; changed.append('active')
        if not kind.created_by_id:
            kind.created_by_id = fallback.pk; changed.append('created_by')
        if changed:
            kind.save(update_fields=changed)

        catalog = ComponentCatalog.objects.filter(component_type_id=kind.pk).select_related('inventory_table').first()
        if catalog is None:
            base = slugify(source.name) or f'tipo-{source.pk}'
            slug = f'componente-{base}'; n = 2
            while InventoryTable.objects.filter(slug=slug).exists():
                slug = f'componente-{base}-{n}'; n += 1
            table = InventoryTable.objects.create(
                name=f'COMPONENTES · {source.name}', slug=slug,
                id_header=source.id_header, id_prefix=f'{(base.upper().replace("-", "")[:6] or "COMP")}-',
                id_width=source.id_width or 5, next_number=1, active=True,
                created_by_id=fallback.pk,
            )
            catalog = ComponentCatalog.objects.create(
                component_type_id=kind.pk, inventory_table_id=table.pk,
                active=True, created_by_id=fallback.pk,
            )
        else:
            table = catalog.inventory_table
            if not catalog.active:
                catalog.active = True; catalog.save(update_fields=['active'])
            if not table.active:
                table.active = True; table.save(update_fields=['active'])

        # Replica todos los campos originales, conservando clave, nombre, tipo
        # y marcas funcionales. No sobreescribe campos existentes.
        position = table.inventory_fields.order_by('-position').values_list('position', flat=True).first() or 0
        for source_field in source.inventory_fields.all().order_by('position', 'pk'):
            if table.inventory_fields.filter(key=source_field.key).exists():
                continue
            position += 1
            InventoryField.objects.create(
                table_id=table.pk, name=source_field.name, key=source_field.key,
                position=position, field_type=source_field.field_type,
                is_primary=source_field.is_primary,
                is_destination_sn=source_field.is_destination_sn,
                is_technician=source_field.is_technician,
            )

        # Campos operativos propios del almacén de componentes. PRECIO queda
        # añadido aunque la tabla original no lo tuviera.
        for key, name, field_type in COMMON_FIELDS:
            if table.inventory_fields.filter(key=key).exists():
                continue
            position += 1
            InventoryField.objects.create(
                table_id=table.pk, name=name, key=key, position=position,
                field_type=field_type,
                is_destination_sn=(key == 'destination_sn'),
                is_technician=(key == 'technician'),
            )


class Migration(migrations.Migration):
    dependencies = [('inventory', '0052_align_customerorder_stock_state')]
    operations = [migrations.RunPython(sync_catalogs, migrations.RunPython.noop)]
