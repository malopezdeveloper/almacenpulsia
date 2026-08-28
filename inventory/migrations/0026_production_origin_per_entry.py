from django.db import migrations, models

ZONES=[("pintura","Pintura"),("calidad","Calidad"),("montaje","Montaje"),("auditoria","Auditoría"),("garantias","Garantías"),("admision","Admisión"),("renove","Renove"),("reparaciones","Reparaciones")]

class Migration(migrations.Migration):
    dependencies=[("inventory","0025_production_origin_and_local_backup")]
    operations=[
        migrations.RemoveField(model_name="userprofile", name="origin_zone"),
        migrations.AlterField(
            model_name="productionentry",
            name="origin_zone",
            field=models.CharField(choices=ZONES, db_index=True, max_length=30),
        ),
    ]
