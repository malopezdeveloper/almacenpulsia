from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('inventory', '0038_unit_work_queue_lifecycle'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='activesecuritysession',
            options={'ordering': ('-last_activity', '-pk')},
        ),
        migrations.AlterModelOptions(
            name='securityaccessevent',
            options={'ordering': ('-created_at', '-pk')},
        ),
        migrations.AlterField(
            model_name='activesecuritysession',
            name='id',
            field=models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID'),
        ),
        migrations.AlterField(
            model_name='component',
            name='status',
            field=models.CharField(
                choices=[
                    ('active', 'Disponible'),
                    ('reserved', 'Reservado'),
                    ('installed', 'Instalado'),
                    ('low', 'Baja'),
                ],
                db_index=True,
                default='active',
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name='securityaccessevent',
            name='id',
            field=models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID'),
        ),
        migrations.AlterField(
            model_name='securityaccesspolicy',
            name='id',
            field=models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID'),
        ),
    ]
