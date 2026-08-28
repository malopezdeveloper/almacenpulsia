from django.db import migrations, models

ZONES=[("pintura","Pintura"),("calidad","Calidad"),("montaje","Montaje"),("auditoria","Auditoría"),("garantias","Garantías"),("admision","Admisión"),("renove","Renove"),("reparaciones","Reparaciones")]

class Migration(migrations.Migration):
    dependencies=[("inventory","0024_backup_disk_config")]
    operations=[
        migrations.AddField(model_name="userprofile",name="origin_zone",field=models.CharField(blank=True,choices=ZONES,db_index=True,max_length=30)),
        migrations.AddField(model_name="productionentry",name="origin_zone",field=models.CharField(blank=True,choices=ZONES,db_index=True,max_length=30)),
        migrations.AddField(model_name="backupdiskconfig",name="mode",field=models.CharField(choices=[("disk","Disco dedicado"),("local","Directorio local")],db_index=True,default="disk",max_length=10)),
        migrations.AddField(model_name="backupdiskconfig",name="local_path",field=models.CharField(blank=True,max_length=500)),
    ]
