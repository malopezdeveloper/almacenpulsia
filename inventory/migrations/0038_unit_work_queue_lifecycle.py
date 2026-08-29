from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('inventory', '0037_component_confirmation_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='unitintervention',
            name='destination_zone',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='unit_interventions_received',
                to='inventory.productionzone',
            ),
        ),
        migrations.AddField(
            model_name='unitintervention',
            name='finished_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='unitintervention',
            name='duration_seconds',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
