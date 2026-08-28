from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies=[("inventory","0023_production_specs_exclusions_processors")]
    operations=[
        migrations.CreateModel(
            name="BackupDiskConfig",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("device",models.CharField(blank=True,max_length=255)),
                ("uuid",models.CharField(blank=True,max_length=128)),
                ("filesystem",models.CharField(blank=True,max_length=32)),
                ("mount_point",models.CharField(default="/mnt/pulsia-backup",max_length=255)),
                ("last_status",models.CharField(blank=True,max_length=20)),
                ("last_error",models.TextField(blank=True)),
                ("updated_at",models.DateTimeField(auto_now=True)),
                ("updated_by",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.PROTECT,related_name="backup_disk_configs_updated",to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
