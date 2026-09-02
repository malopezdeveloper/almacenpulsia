from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('inventory', '0045_stock_creator_gestor'),
    ]

    operations = [
        migrations.CreateModel(
            name='Installation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('installed_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('source', models.CharField(choices=[('warehouse', 'Bodega / almacén'), ('order', 'Pedido'), ('board', 'Pizarra'), ('reservation', 'Reserva')], db_index=True, default='reservation', max_length=16)),
                ('unit_serial_number', models.CharField(db_index=True, max_length=180)),
                ('component_reference', models.CharField(blank=True, db_index=True, max_length=200)),
                ('component_type', models.CharField(blank=True, db_index=True, max_length=160)),
                ('inventory_table_name', models.CharField(blank=True, max_length=120)),
                ('inventory_internal_id', models.CharField(blank=True, db_index=True, max_length=160)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('component', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='installation_events', to='inventory.component')),
                ('inventory_record', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='installation_events', to='inventory.inventoryrecord')),
                ('reservation', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='installation_event', to='inventory.componentreservation')),
                ('technician', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='signed_installations', to=settings.AUTH_USER_MODEL)),
                ('unit', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='installation_events', to='inventory.orderunit')),
            ],
            options={'ordering': ('-installed_at', '-pk')},
        ),
    ]
