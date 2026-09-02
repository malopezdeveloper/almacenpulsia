from django.db import migrations
from django.utils.text import slugify


COMMON_FIELDS = (
    ('price', 'PRECIO', 'number'),
    ('delivery_date', 'FECHA DE ENTREGA', 'date'),
    ('reservation_date', 'FECHA DE RESERVA', 'date'),
    ('technician', 'TÉCNICO', 'text'),
    ('destination_sn', 'SN DE DESTINO', 'text'),
)


def bootstrap(apps, schema_editor):
    ComponentType = apps.get_model('inventory', 'ComponentType')
    ComponentCatalog = apps.get_model('inventory', 'ComponentCatalog')
    InventoryTable = apps.get_model('inventory', 'InventoryTable')
    InventoryField = apps.get_model('inventory', 'InventoryField')
    User = apps.get_model('auth', 'User')

    fallback_user = User.objects.filter(is_active=True, is_superuser=True).order_by('pk').first() or User.objects.filter(is_active=True).order_by('pk').first()
    if fallback_user is None:
        return

    for kind in ComponentType.objects.all().order_by('pk'):
        if ComponentCatalog.objects.filter(component_type_id=kind.pk).exists():
            continue
        base = slugify(kind.name) or f'componente-{kind.pk}'
        slug = f'componente-{base}'
        n = 2
        while InventoryTable.objects.filter(slug=slug).exists():
            slug = f'componente-{base}-{n}'
            n += 1
        table = InventoryTable.objects.create(
            name=f'COMPONENTES · {kind.name}', slug=slug, id_header='ID',
            id_prefix=f'{(base.upper().replace("-", "")[:6] or "COMP")}-',
            id_width=5, next_number=1, active=kind.active, created_by_id=kind.created_by_id or fallback_user.pk,
        )
        InventoryField.objects.create(table=table, name='ID', key='id', position=0, field_type='text', is_primary=True)
        for pos, (key, name, field_type) in enumerate(COMMON_FIELDS, start=1):
            InventoryField.objects.create(
                table=table, name=name, key=key, position=pos, field_type=field_type,
                is_destination_sn=(key == 'destination_sn'), is_technician=(key == 'technician')
            )
        ComponentCatalog.objects.create(component_type=kind, inventory_table=table, active=kind.active, created_by_id=kind.created_by_id or fallback_user.pk)


class Migration(migrations.Migration):
    dependencies = [('inventory', '0047_component_catalog')]
    operations = [migrations.RunPython(bootstrap, migrations.RunPython.noop)]
