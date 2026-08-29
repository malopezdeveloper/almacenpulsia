from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0030_saved_queries"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AreaResponsibility",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("responsibility", models.CharField(choices=[("production", "Responsable de Producción"), ("purchasing", "Responsable de Compras"), ("sales", "Responsable de Ventas"), ("technical", "Responsable Técnico")], db_index=True, max_length=20, unique=True)),
                ("assigned_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("assigned_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="area_responsibilities_assigned", to=settings.AUTH_USER_MODEL)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="area_responsibilities", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("responsibility",)},
        ),
        migrations.CreateModel(
            name="AreaResponsibilityHistory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("responsibility", models.CharField(choices=[("production", "Responsable de Producción"), ("purchasing", "Responsable de Compras"), ("sales", "Responsable de Ventas"), ("technical", "Responsable Técnico")], db_index=True, max_length=20)),
                ("action", models.CharField(choices=[("assigned", "Asignada"), ("transferred", "Transferida"), ("unassigned", "Retirada")], max_length=12)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("changed_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="area_responsibility_changes", to=settings.AUTH_USER_MODEL)),
                ("previous_user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="area_responsibility_history_previous", to=settings.AUTH_USER_MODEL)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="area_responsibility_history", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-created_at", "-pk")},
        ),
    ]
