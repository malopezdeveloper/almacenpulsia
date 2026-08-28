from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

PROCESSORS = """
INTEL CORE I3-4005U
INTEL CORE I3-4010U
INTEL CORE I3-4030U
INTEL CORE I3-4130
INTEL CORE I3-4150
INTEL CORE I3-4160
INTEL CORE I5-4200U
INTEL CORE I5-4210U
INTEL CORE I5-4300U
INTEL CORE I5-4310U
INTEL CORE I5-4570
INTEL CORE I5-4590
INTEL CORE I7-4600U
INTEL CORE I7-4770
INTEL CORE I3-5005U
INTEL CORE I5-5200U
INTEL CORE I5-5300U
INTEL CORE I7-5500U
INTEL CORE I7-5600U
INTEL CORE I3-6100
INTEL CORE I3-6100U
INTEL CORE I5-6200U
INTEL CORE I5-6300U
INTEL CORE I5-6500
INTEL CORE I7-6500U
INTEL CORE I7-6600U
INTEL CORE I7-6700
INTEL CORE I3-7100
INTEL CORE I3-7100U
INTEL CORE I5-7200U
INTEL CORE I5-7300U
INTEL CORE I5-7400
INTEL CORE I7-7500U
INTEL CORE I7-7600U
INTEL CORE I7-7700
INTEL CORE I3-8100
INTEL CORE I3-8130U
INTEL CORE I5-8250U
INTEL CORE I5-8350U
INTEL CORE I5-8400
INTEL CORE I5-8500
INTEL CORE I7-8550U
INTEL CORE I7-8650U
INTEL CORE I7-8700
INTEL CORE I3-9100
INTEL CORE I5-9400
INTEL CORE I5-9500
INTEL CORE I7-9700
INTEL CORE I3-10100
INTEL CORE I3-10110U
INTEL CORE I5-10210U
INTEL CORE I5-10310U
INTEL CORE I5-10400
INTEL CORE I5-10500
INTEL CORE I7-10510U
INTEL CORE I7-10610U
INTEL CORE I7-10700
INTEL CORE I3-1115G4
INTEL CORE I5-1135G7
INTEL CORE I5-1145G7
INTEL CORE I5-11500
INTEL CORE I7-1165G7
INTEL CORE I7-11700
INTEL CORE I7-1185G7
INTEL CORE I3-12100
INTEL CORE I3-1215U
INTEL CORE I5-1235U
INTEL CORE I5-1245U
INTEL CORE I5-12500
INTEL CORE I7-1255U
INTEL CORE I7-1265U
INTEL CORE I7-12700
INTEL CORE I3-13100
INTEL CORE I3-1315U
INTEL CORE I5-1335U
INTEL CORE I5-1345U
INTEL CORE I5-13500
INTEL CORE I7-1355U
INTEL CORE I7-1365U
INTEL CORE I7-13700
INTEL CORE I5-14400
INTEL CORE I7-14700
INTEL CORE ULTRA 5 125U
INTEL CORE ULTRA 5 135U
INTEL CORE ULTRA 5 125H
INTEL CORE ULTRA 7 155U
INTEL CORE ULTRA 7 165U
INTEL CORE ULTRA 7 155H
INTEL XEON E3-1220 V5
INTEL XEON E3-1240 V5
INTEL XEON E3-1270 V5
INTEL XEON E3-1225 V6
INTEL XEON E3-1240 V6
INTEL XEON E-2124
INTEL XEON E-2134
AMD ATHLON 3000G
AMD ATHLON GOLD 3150U
AMD ATHLON SILVER 3050U
AMD ATHLON PRO 300GE
AMD ATHLON GOLD PRO 3150G
AMD ATHLON GOLD PRO 3150GE
AMD ATHLON SILVER PRO 3125GE
AMD RYZEN 3 2200G
AMD RYZEN 3 PRO 2200G
AMD RYZEN 3 PRO 3200G
AMD RYZEN 3 PRO 3200GE
AMD RYZEN 3 4300U
AMD RYZEN 3 PRO 4350G
AMD RYZEN 3 PRO 4350GE
AMD RYZEN 5 2400G
AMD RYZEN 5 PRO 2400G
AMD RYZEN 5 PRO 3400G
AMD RYZEN 5 PRO 3400GE
AMD RYZEN 5 PRO 3600
AMD RYZEN 5 4500U
AMD RYZEN 5 4600U
AMD RYZEN 5 4600H
AMD RYZEN 5 PRO 4650G
AMD RYZEN 5 PRO 4650GE
AMD RYZEN 5 PRO 4650U
AMD RYZEN 5 5500U
AMD RYZEN 5 5600U
AMD RYZEN 5 PRO 5650G
AMD RYZEN 5 PRO 5650GE
AMD RYZEN 5 PRO 5650U
AMD RYZEN 7 PRO 3700
AMD RYZEN 7 4700U
AMD RYZEN 7 4800U
AMD RYZEN 7 4800H
AMD RYZEN 7 PRO 4750G
AMD RYZEN 7 PRO 4750GE
AMD RYZEN 7 PRO 4750U
AMD RYZEN 7 5700U
AMD RYZEN 7 5800U
AMD RYZEN 7 PRO 5750G
AMD RYZEN 7 PRO 5750GE
AMD RYZEN 7 PRO 5850U
APPLE M1
APPLE M1 PRO
APPLE M1 MAX
APPLE M1 ULTRA
APPLE M2
APPLE M2 PRO
APPLE M2 MAX
APPLE M2 ULTRA
APPLE M3
APPLE M3 PRO
APPLE M3 MAX
APPLE M4
APPLE M4 PRO
APPLE M4 MAX
"""

def seed_processors(apps, schema_editor):
    Processor = apps.get_model("inventory", "ProductionProcessor")
    for raw in PROCESSORS.splitlines():
        name = " ".join(raw.strip().split()).upper()
        if name:
            Processor.objects.get_or_create(name=name)

def noop(apps, schema_editor):
    pass

class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0022_production_model_mysql_source"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.AddField(
            model_name="productionmodel",
            name="is_active",
            field=models.BooleanField(db_index=True, default=True),
        ),
        migrations.CreateModel(
            name="ProductionModelExclusion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(db_index=True, max_length=160, unique=True)),
                ("reason", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("excluded_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="production_model_exclusions_created", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="ProductionProcessor",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(db_index=True, max_length=160, unique=True)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="production_processors_created", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.AddField(
            model_name="productionentry",
            name="ram_gb",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="productionentry",
            name="disk_gb",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="productionentry",
            name="processor_name",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="productionentry",
            name="processor",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="entries", to="inventory.productionprocessor"),
        ),
        migrations.RunPython(seed_processors, noop),
    ]
