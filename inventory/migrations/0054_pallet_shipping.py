from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0053_sync_component_catalogs_from_inventory'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Pallet',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('open', 'Abierto'), ('shipped', 'Enviado')], db_index=True, default='open', max_length=12)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('shipped_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('recipient', models.CharField(blank=True, max_length=250)),
                ('shipping_data', models.JSONField(blank=True, default=dict)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='pallets_created', to=settings.AUTH_USER_MODEL)),
                ('shipped_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='pallets_shipped', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ('-id',)},
        ),
        migrations.CreateModel(
            name='PalletUnit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('added_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('added_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='pallet_units_added', to=settings.AUTH_USER_MODEL)),
                ('pallet', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='units', to='inventory.pallet')),
                ('unit', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='pallet_membership', to='inventory.orderunit')),
            ],
            options={'ordering': ('added_at', 'id')},
        ),
    ]
