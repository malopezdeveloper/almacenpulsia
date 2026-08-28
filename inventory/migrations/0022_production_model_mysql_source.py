from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0021_production_model_catalog"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ProductionModelMySQLSource",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("host", models.CharField(max_length=255)),
                ("port", models.PositiveIntegerField(default=3306)),
                ("database", models.CharField(max_length=128)),
                ("username", models.CharField(max_length=128)),
                ("encrypted_password", models.TextField(blank=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="production_mysql_sources_updated", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "Origen MySQL de modelos de producción"},
        ),
    ]
