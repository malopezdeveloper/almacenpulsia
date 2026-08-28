from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies=[("inventory","0012_ipban_permanent"),migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations=[migrations.CreateModel(name="NetworkReservationRequest",fields=[
        ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
        ("ip_address",models.GenericIPAddressField(db_index=True)),
        ("prefix_length",models.PositiveSmallIntegerField(default=24)),
        ("gateway",models.GenericIPAddressField(blank=True,null=True)),
        ("mac_address",models.CharField(blank=True,db_index=True,max_length=32)),
        ("interface_name",models.CharField(blank=True,max_length=160)),
        ("hostname",models.CharField(blank=True,max_length=160)),
        ("platform",models.CharField(blank=True,max_length=80)),
        ("status",models.CharField(choices=[("pending","Pendiente"),("applied","Aplicada"),("partial","Parcial"),("failed","Error")],db_index=True,default="pending",max_length=12)),
        ("dhcp_reserved",models.BooleanField(default=False)),
        ("dns_updated",models.BooleanField(default=False)),
        ("details",models.JSONField(blank=True,default=dict)),
        ("message",models.TextField(blank=True)),
        ("requested_at",models.DateTimeField(auto_now_add=True,db_index=True)),
        ("completed_at",models.DateTimeField(blank=True,null=True)),
        ("requested_by",models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name="network_reservation_requests",to=settings.AUTH_USER_MODEL)),
    ],options={"ordering": ("-requested_at","-pk")})]
