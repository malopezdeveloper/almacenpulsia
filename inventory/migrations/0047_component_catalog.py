from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('inventory', '0046_installation_event'),
    ]

    operations = [
        migrations.CreateModel(
            name='ComponentCatalog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('active', models.BooleanField(db_index=True, default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('component_type', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='catalog', to='inventory.componenttype')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='component_catalogs_created', to=settings.AUTH_USER_MODEL)),
                ('inventory_table', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='component_catalog', to='inventory.inventorytable')),
            ],
            options={'ordering': ('component_type__name',)},
        ),
    ]
