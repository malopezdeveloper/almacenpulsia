from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('inventory', '0035_component_reservation_flow'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name='UnitIntervention',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source', models.CharField(choices=[('local','Lote/Pedido local'),('aiken','AIKEN'),('manual','Alta manual confirmada')], db_index=True, default='local', max_length=12)),
                ('source_snapshot', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('unit', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='interventions', to='inventory.orderunit')),
                ('worker', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='unit_interventions', to=settings.AUTH_USER_MODEL)),
                ('zone', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='unit_interventions', to='inventory.productionzone')),
            ],
            options={'ordering': ('-created_at','-pk')},
        ),
        migrations.AddIndex(model_name='unitintervention', index=models.Index(fields=['unit','created_at'], name='unit_intervention_idx')),
        migrations.CreateModel(
            name='UnitAlertOrigin',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('alert', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='origin_trace', to='inventory.procurementalert')),
                ('intervention', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='alerts', to='inventory.unitintervention')),
                ('origin_worker', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='unit_alerts_originated', to=settings.AUTH_USER_MODEL)),
                ('origin_zone', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='unit_alerts_originated', to='inventory.productionzone')),
            ],
        ),
        migrations.CreateModel(
            name='ReservationInstallation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('installed_at', models.DateTimeField(auto_now_add=True)),
                ('installed_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='component_installation_events', to=settings.AUTH_USER_MODEL)),
                ('intervention', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='component_installations', to='inventory.unitintervention')),
                ('reservation', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='installation_trace', to='inventory.componentreservation')),
            ],
        ),
        migrations.CreateModel(
            name='RepairConfirmation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('confirmed_at', models.DateTimeField(auto_now_add=True)),
                ('observations', models.TextField(blank=True)),
                ('confirmed_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='repair_confirmations', to=settings.AUTH_USER_MODEL)),
                ('intervention', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='repair_confirmations', to='inventory.unitintervention')),
                ('repair', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='confirmation', to='inventory.repair')),
            ],
        ),
    ]
