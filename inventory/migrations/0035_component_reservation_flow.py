from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('inventory', '0034_unit_lifecycle_order_status'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='OrderComponentAuthorization',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('approved_quantity', models.PositiveIntegerField(default=0)),
                ('unlimited', models.BooleanField(default=False)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('component_type', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='order_authorizations', to='inventory.componenttype')),
                ('order', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='component_authorizations', to='inventory.customerorder')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='component_authorizations_updated', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name='ordercomponentauthorization',
            constraint=models.UniqueConstraint(fields=('order', 'component_type'), name='unique_order_component_authorization'),
        ),
        migrations.CreateModel(
            name='ComponentIncreaseRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('requested_quantity', models.PositiveIntegerField(default=1)),
                ('status', models.CharField(choices=[('pending', 'Pendiente'), ('approved', 'Aprobada'), ('rejected', 'Rechazada'), ('fulfilled', 'Atendida')], db_index=True, default='pending', max_length=12)),
                ('requested_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('observations', models.TextField(blank=True)),
                ('component_type', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='increase_requests', to='inventory.componenttype')),
                ('order', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='component_increase_requests', to='inventory.customerorder')),
                ('requested_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='component_increase_requests', to=settings.AUTH_USER_MODEL)),
                ('resolved_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='component_increase_requests_resolved', to=settings.AUTH_USER_MODEL)),
                ('unit', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='component_increase_requests', to='inventory.orderunit')),
            ],
            options={'ordering': ('-requested_at', '-pk')},
        ),
        migrations.CreateModel(
            name='ReservationAllocation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source', models.CharField(choices=[('warehouse', 'Bodega'), ('order', 'Componentes autorizados del pedido')], db_index=True, max_length=16)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('authorization', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='allocations', to='inventory.ordercomponentauthorization')),
                ('order', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='component_allocations', to='inventory.customerorder')),
                ('reservation', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='allocation', to='inventory.componentreservation')),
            ],
        ),
    ]
