from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def ensure_stock_order(apps, schema_editor):
    CustomerOrder = apps.get_model('inventory', 'CustomerOrder')
    stock = CustomerOrder.objects.filter(name__iexact='stock', customer__isnull=True).first()
    if not stock:
        CustomerOrder.objects.create(
            name='STOCK', customer=None, brand='', model='', lot='', processor='', ram='', disk='',
            status='open', visual_family='green', created_by_id=1 if apps.get_model(*settings.AUTH_USER_MODEL.split('.')).objects.filter(pk=1).exists() else apps.get_model(*settings.AUTH_USER_MODEL.split('.')).objects.order_by('pk').values_list('pk', flat=True).first()
        )


class Migration(migrations.Migration):
    dependencies = [('inventory', '0040_physical_unit_location')]

    operations = [
        migrations.AlterField(
            model_name='customerorder', name='customer',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='orders', to='inventory.customer'),
        ),
        migrations.CreateModel(
            name='BoardPriority',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('active', models.BooleanField(db_index=True, default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='board_priorities_created', to=settings.AUTH_USER_MODEL)),
                ('order', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='board_priorities', to='inventory.customerorder')),
                ('zone', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='board_priorities', to='inventory.productionzone')),
            ],
            options={'ordering': ('zone__position', 'zone__name', 'order__name', 'pk')},
        ),
        migrations.AddConstraint(
            model_name='boardpriority',
            constraint=models.UniqueConstraint(fields=('order', 'zone'), name='unique_board_priority_order_zone'),
        ),
        migrations.RunPython(ensure_stock_order, migrations.RunPython.noop),
    ]
