from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import datetime
import re


EXCLUDED_TOKENS={"id","nota","notas","fecha","fehca","sn","serie","serial"}


def uppercase_existing_inventory_text(apps, schema_editor):
    InventoryField=apps.get_model("inventory","InventoryField")
    InventoryRecord=apps.get_model("inventory","InventoryRecord")
    fields_by_table={}
    for field in InventoryField.objects.filter(field_type="text",is_primary=False):
        label=(f"{field.key} {field.name}").casefold()
        words=set(re.findall(r"[a-záéíóúñ0-9]+",label))
        excluded=field.is_destination_sn or bool(words.intersection(EXCLUDED_TOKENS))
        if not excluded:
            fields_by_table.setdefault(field.table_id,[]).append(field.key)
    for record in InventoryRecord.objects.all().iterator():
        keys=fields_by_table.get(record.table_id,[])
        if not keys:
            continue
        data=dict(record.data or {})
        changed=False
        for key in keys:
            value=data.get(key)
            if isinstance(value,str) and value:
                upper=value.upper()
                if upper!=value:
                    data[key]=upper
                    changed=True
        if changed:
            InventoryRecord.objects.filter(pk=record.pk).update(data=data)


class Migration(migrations.Migration):
    dependencies=[("inventory","0014_guest_access_upgrade")]

    operations=[
        migrations.AddField(
            model_name="userprofile",
            name="archived_at",
            field=models.DateTimeField(blank=True,db_index=True,null=True),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="archived_by",
            field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.PROTECT,related_name="inventory_users_archived",to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="archived_reason",
            field=models.CharField(blank=True,max_length=300),
        ),
        migrations.CreateModel(
            name="BackupSchedule",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("enabled",models.BooleanField(default=False)),
                ("run_time",models.TimeField(default=datetime.time(2,0))),
                ("destination",models.CharField(blank=True,max_length=500)),
                ("retention",models.PositiveIntegerField(default=30)),
                ("last_run_at",models.DateTimeField(blank=True,null=True)),
                ("last_status",models.CharField(blank=True,max_length=20)),
                ("last_error",models.TextField(blank=True)),
                ("updated_at",models.DateTimeField(auto_now=True)),
                ("updated_by",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.PROTECT,related_name="backup_schedules_updated",to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.RunPython(uppercase_existing_inventory_text,migrations.RunPython.noop),
    ]
