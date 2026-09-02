from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('inventory', '0051_expand_technical_fields_for_postgresql')]

    operations = [
        # 0041 hizo nullable la columna física mediante SeparateDatabaseAndState,
        # pero dejó el estado de migraciones desalineado y apps.py lo corregía
        # dinámicamente. PostgreSQL ya es el motor definitivo: registramos aquí
        # el estado real para que makemigrations --check quede limpio.
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AlterField(
                    model_name='customerorder',
                    name='customer',
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name='orders',
                        to='inventory.customer',
                    ),
                ),
            ],
        ),
    ]
