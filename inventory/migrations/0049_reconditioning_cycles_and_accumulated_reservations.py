from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('inventory', '0048_bootstrap_component_catalogs')]

    operations = [
        migrations.RemoveConstraint(
            model_name='orderunit',
            name='one_unit_cycle_per_order',
        ),
        migrations.AddIndex(
            model_name='orderunit',
            index=models.Index(fields=['physical_unit', '-imported_at'], name='orderunit_cycle_idx'),
        ),
        migrations.RemoveConstraint(
            model_name='componentreservation',
            name='one_active_component_reservation',
        ),
    ]
