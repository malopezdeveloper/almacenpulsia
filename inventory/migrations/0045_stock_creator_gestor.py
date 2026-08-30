from django.db import migrations


def assign_stock_creator(apps, schema_editor):
    CustomerOrder = apps.get_model('inventory', 'CustomerOrder')
    BusinessRoleAssignment = apps.get_model('inventory', 'BusinessRoleAssignment')
    User = apps.get_model('auth', 'User')

    stock = (
        CustomerOrder.objects
        .filter(name__iexact='stock', customer__isnull=True)
        .order_by('pk')
        .first()
    )
    if stock is None:
        return

    gestor_user_id = (
        BusinessRoleAssignment.objects
        .filter(role__active=True, role__code='gestor', user__is_active=True)
        .order_by('user_id')
        .values_list('user_id', flat=True)
        .first()
    )
    if gestor_user_id is None:
        gestor_user_id = (
            User.objects.filter(is_active=True, is_superuser=True)
            .order_by('pk')
            .values_list('pk', flat=True)
            .first()
        )
    if gestor_user_id is not None and stock.created_by_id != gestor_user_id:
        stock.created_by_id = gestor_user_id
        stock.save(update_fields=['created_by'])


class Migration(migrations.Migration):
    dependencies = [('inventory', '0044_stock_fixed_id_one')]
    operations = [migrations.RunPython(assign_stock_creator, migrations.RunPython.noop)]
