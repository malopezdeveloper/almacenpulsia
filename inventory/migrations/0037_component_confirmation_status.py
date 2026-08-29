from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('inventory', '0036_unit_workflow_stabilization')]
    operations = [
        migrations.RemoveConstraint(model_name='componentreservation', name='one_active_component_reservation'),
        migrations.AlterField(
            model_name='componentreservation',
            name='status',
            field=models.CharField(choices=[('active','Reservado'),('installed','Instalado pendiente de confirmación'),('confirmed','Reparación confirmada'),('cancelled','Cancelada')], db_index=True, default='active', max_length=16),
        ),
        migrations.AddConstraint(
            model_name='componentreservation',
            constraint=models.UniqueConstraint(condition=models.Q(('status__in',['active','installed','confirmed'])), fields=('component',), name='one_active_component_reservation'),
        ),
    ]
