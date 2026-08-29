from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_traceability(apps,schema_editor):
    Component=apps.get_model('inventory','Component')
    ComponentType=apps.get_model('inventory','ComponentType')
    Repair=apps.get_model('inventory','Repair')
    Reservation=apps.get_model('inventory','ComponentReservation')
    for component in Component.objects.all().iterator():
        name=(component.component_type or '').strip()
        if name:
            kind,_=ComponentType.objects.get_or_create(name=name)
            component.component_kind_id=kind.pk
            component.save(update_fields=['component_kind'])
    for repair in Repair.objects.all().iterator():
        name=(repair.repair_type or '').strip()
        if name:
            kind,_=ComponentType.objects.get_or_create(name=name)
            repair.component_type_id=kind.pk
            repair.save(update_fields=['component_type'])
    for reservation in Reservation.objects.select_related('repair').all().iterator():
        if reservation.repair_id:
            reservation.unit_id=reservation.repair.unit_id
            if reservation.status=='delivered':
                reservation.status='installed'
                reservation.installed_by_id=reservation.technician_id
                reservation.installed_at=reservation.resolved_at or reservation.reserved_at
            reservation.save(update_fields=['unit','status','installed_by','installed_at'])


class Migration(migrations.Migration):
    dependencies=[('inventory','0028_orders_repairs_roles'),migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations=[
        migrations.CreateModel(name='ComponentType',fields=[('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),('name',models.CharField(db_index=True,max_length=160,unique=True)),('active',models.BooleanField(db_index=True,default=True)),('created_at',models.DateTimeField(auto_now_add=True)),('created_by',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.PROTECT,related_name='component_types_created',to=settings.AUTH_USER_MODEL))]),
        migrations.AddField(model_name='orderunit',name='aiken_unit_id',field=models.CharField(blank=True,db_index=True,max_length=80)),
        migrations.AddField(model_name='component',name='price',field=models.DecimalField(decimal_places=2,default=0,max_digits=12)),
        migrations.AddField(model_name='component',name='component_kind',field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.PROTECT,related_name='components',to='inventory.componenttype')),
        migrations.AlterField(model_name='component',name='status',field=models.CharField(choices=[('active','Disponible'),('reserved','Reservado'),('installed','Reservado e instalado'),('low','Baja')],db_index=True,default='active',max_length=16)),
        migrations.AddField(model_name='repair',name='component_type',field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.PROTECT,related_name='repairs',to='inventory.componenttype')),
        migrations.AlterField(model_name='procurementalert',name='repair',field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.CASCADE,related_name='procurement_alerts',to='inventory.repair')),
        migrations.AddField(model_name='procurementalert',name='unit',field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.CASCADE,related_name='procurement_alerts',to='inventory.orderunit')),
        migrations.AddField(model_name='procurementalert',name='component_type',field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.PROTECT,related_name='procurement_alerts',to='inventory.componenttype')),
        migrations.RemoveConstraint(model_name='componentreservation',name='one_active_component_reservation'),
        migrations.AlterField(model_name='componentreservation',name='repair',field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.PROTECT,related_name='component_reservations',to='inventory.repair')),
        migrations.AddField(model_name='componentreservation',name='unit',field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.PROTECT,related_name='component_reservations',to='inventory.orderunit')),
        migrations.AddField(model_name='componentreservation',name='installed_by',field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.PROTECT,related_name='component_installations',to=settings.AUTH_USER_MODEL)),
        migrations.AddField(model_name='componentreservation',name='installed_at',field=models.DateTimeField(blank=True,null=True)),
        migrations.AlterField(model_name='componentreservation',name='status',field=models.CharField(choices=[('active','Reservado'),('installed','Reservado e instalado'),('cancelled','Cancelada')],db_index=True,default='active',max_length=16)),
        migrations.AddConstraint(model_name='componentreservation',constraint=models.UniqueConstraint(condition=models.Q(status__in=['active','installed']),fields=('component',),name='one_active_component_reservation')),
        migrations.AlterField(model_name='rma',name='component',field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.PROTECT,related_name='rmas',to='inventory.component')),
        migrations.AlterField(model_name='rma',name='supplier',field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.PROTECT,related_name='rmas',to='inventory.supplier')),
        migrations.AddField(model_name='rma',name='component_type',field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.PROTECT,related_name='rmas',to='inventory.componenttype')),
        migrations.AddField(model_name='rma',name='unit',field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.PROTECT,related_name='rmas',to='inventory.orderunit')),
        migrations.AddField(model_name='rma',name='reservation',field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.PROTECT,related_name='rmas',to='inventory.componentreservation')),
        migrations.AddField(model_name='rma',name='origin',field=models.CharField(choices=[('supplier','Proveedor'),('original','Original de la unidad'),('warehouse','Reserva de almacén')],db_index=True,default='supplier',max_length=16)),
        migrations.RunPython(backfill_traceability,migrations.RunPython.noop),
    ]
