from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

INITIAL_ZONES = [
    (10, "pintura", "Pintura"),
    (20, "calidad", "Calidad"),
    (30, "montaje", "Montaje"),
    (40, "auditoria", "Auditoría"),
    (50, "garantias", "Garantías"),
    (60, "admision", "Admisión"),
    (70, "renove", "Renove"),
    (80, "reparaciones", "Reparaciones"),
    (90, "teclados", "Teclados"),
    (100, "direccion", "Dirección"),
]


def seed_and_normalize(apps, schema_editor):
    Zone = apps.get_model("inventory", "ProductionZone")
    Reservation = apps.get_model("inventory", "Reservation")
    for position, code, name in INITIAL_ZONES:
        Zone.objects.get_or_create(code=code, defaults={"name": name, "position": position, "is_active": True})
    aliases = {
        "Pintura": "pintura", "Montaje": "montaje", "Calidad": "calidad",
        "Reparaciones": "reparaciones", "Auditoria": "auditoria",
        "Auditoría": "auditoria", "PlanRenove": "renove", "Renove": "renove",
        "Direccion": "direccion", "Dirección": "direccion", "Garantías": "garantias",
        "Garantias": "garantias", "Admisión": "admision", "Admision": "admision",
        "Teclados": "teclados",
    }
    for old, new in aliases.items():
        Reservation.objects.filter(destination=old).update(destination=new)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("inventory", "0026_production_origin_per_entry")]
    operations = [
        migrations.CreateModel(
            name="ProductionZone",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.SlugField(db_index=True, max_length=50, unique=True)),
                ("name", models.CharField(max_length=100, unique=True)),
                ("position", models.PositiveIntegerField(db_index=True, default=0)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="production_zones_created", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["position", "name"]},
        ),
        migrations.AlterField(model_name="reservation", name="destination", field=models.CharField(max_length=50)),
        migrations.AlterField(model_name="productionentry", name="origin_zone", field=models.CharField(db_index=True, max_length=50)),
        migrations.AlterField(model_name="productionentry", name="zone", field=models.CharField(db_index=True, help_text="Zona de destino", max_length=50)),
        migrations.RunPython(seed_and_normalize, noop_reverse),
    ]
