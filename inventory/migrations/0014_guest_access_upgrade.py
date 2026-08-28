from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0013_networkreservationrequest"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="role",
            field=models.CharField(
                choices=[("guest", "Invitado"), ("user", "Usuario")],
                db_index=True,
                default="user",
                max_length=12,
            ),
        ),
        migrations.CreateModel(
            name="AccessUpgradeRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("requested_ip", models.GenericIPAddressField(blank=True, null=True)),
                ("status", models.CharField(choices=[("pending", "Pendiente"), ("approved", "Aprobada"), ("denied", "Denegada")], db_index=True, default="pending", max_length=12)),
                ("requested_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("decision_note", models.CharField(blank=True, max_length=300)),
                ("decided_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="access_upgrade_decisions", to=settings.AUTH_USER_MODEL)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="access_upgrade_request", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-requested_at", "-pk")},
        ),
    ]
