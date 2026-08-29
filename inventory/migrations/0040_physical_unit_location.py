from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('inventory', '0039_model_state_alignment'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PhysicalUnitLocation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('entered_at', models.DateTimeField(db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('intervention', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='location_state', to='inventory.unitintervention')),
                ('physical_unit', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='production_location', to='inventory.physicalunit')),
                ('unit', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='location_states', to='inventory.orderunit')),
                ('worker', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='physical_unit_locations', to=settings.AUTH_USER_MODEL)),
                ('zone', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='physical_units_here', to='inventory.productionzone')),
            ],
            options={'ordering': ('zone__position', 'entered_at', 'pk')},
        ),
    ]
