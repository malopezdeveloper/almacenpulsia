from django.conf import settings
from django.db import migrations,models
import django.db.models.deletion


def migrate_units(apps,schema_editor):
    PhysicalUnit=apps.get_model('inventory','PhysicalUnit'); OrderUnit=apps.get_model('inventory','OrderUnit')
    for u in OrderUnit.objects.all().order_by('pk'):
        p,_=PhysicalUnit.objects.get_or_create(serial_number=u.serial_number,defaults={'brand':u.brand,'model':u.model,'processor':u.processor,'ram':u.ram,'disk':u.disk})
        u.physical_unit=p;u.save(update_fields=['physical_unit'])

class Migration(migrations.Migration):
    dependencies=[('inventory','0033_development_batch'),migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations=[
      migrations.CreateModel(name='PhysicalUnit',fields=[('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),('serial_number',models.CharField(db_index=True,max_length=180,unique=True)),('brand',models.CharField(blank=True,max_length=160)),('model',models.CharField(blank=True,max_length=180)),('processor',models.CharField(blank=True,max_length=180)),('ram',models.CharField(blank=True,max_length=80)),('disk',models.CharField(blank=True,max_length=80)),('created_at',models.DateTimeField(auto_now_add=True))]),
      migrations.AddField(model_name='customerorder',name='status',field=models.CharField(choices=[('open','Abierto'),('closed','Cerrado')],db_index=True,default='open',max_length=12)),
      migrations.AddField(model_name='customerorder',name='visual_family',field=models.CharField(choices=[('green','Verde'),('brown','Marrón')],default='green',max_length=12)),
      migrations.AddField(model_name='customerorder',name='closed_at',field=models.DateTimeField(blank=True,null=True)),
      migrations.AddField(model_name='customerorder',name='closed_by',field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.PROTECT,related_name='customer_orders_closed',to=settings.AUTH_USER_MODEL)),
      migrations.AddField(model_name='orderunit',name='physical_unit',field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.PROTECT,related_name='order_cycles',to='inventory.physicalunit')),
      migrations.AlterField(model_name='orderunit',name='serial_number',field=models.CharField(db_index=True,max_length=180)),
      migrations.RunPython(migrate_units,migrations.RunPython.noop),
      migrations.AlterField(model_name='orderunit',name='physical_unit',field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name='order_cycles',to='inventory.physicalunit')),
      migrations.AddConstraint(model_name='orderunit',constraint=models.UniqueConstraint(fields=('order','physical_unit'),name='one_unit_cycle_per_order')),
      migrations.CreateModel(name='OrderStatusEvent',fields=[('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),('action',models.CharField(choices=[('closed','Cerrado'),('reopened','Reabierto')],max_length=12)),('created_at',models.DateTimeField(auto_now_add=True)),('order',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='status_events',to='inventory.customerorder')),('user',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name='order_status_events',to=settings.AUTH_USER_MODEL))],options={'ordering':('-created_at','-pk')})
    ]