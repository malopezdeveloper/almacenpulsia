from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('inventory', '0050_recambios_zone')]
    operations = [
        migrations.AlterField(model_name='physicalunit', name='processor', field=models.CharField(blank=True, max_length=500)),
        migrations.AlterField(model_name='physicalunit', name='ram', field=models.CharField(blank=True, max_length=500)),
        migrations.AlterField(model_name='physicalunit', name='disk', field=models.CharField(blank=True, max_length=500)),
        migrations.AlterField(model_name='customerorder', name='processor', field=models.CharField(blank=True, max_length=500)),
        migrations.AlterField(model_name='customerorder', name='ram', field=models.CharField(blank=True, max_length=500)),
        migrations.AlterField(model_name='customerorder', name='disk', field=models.CharField(blank=True, max_length=500)),
        migrations.AlterField(model_name='orderunit', name='aiken_unit_id', field=models.CharField(blank=True, db_index=True, max_length=180)),
        migrations.AlterField(model_name='orderunit', name='processor', field=models.CharField(blank=True, max_length=500)),
        migrations.AlterField(model_name='orderunit', name='ram', field=models.CharField(blank=True, max_length=500)),
        migrations.AlterField(model_name='orderunit', name='disk', field=models.CharField(blank=True, max_length=500)),
    ]
