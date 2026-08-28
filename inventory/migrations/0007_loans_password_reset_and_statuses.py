import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('inventory', '0006_chatmessage_reservationview'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='password_reset_requested_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='password_reset_authorized_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='inventoryrecord',
            name='status',
            field=models.CharField(choices=[('available','Disponible'),('reserved','Reservado'),('loaned','Prestado'),('assigned','Entregado / instalado'),('scrapped','Baja / merma'),('incident','Incidencia')], db_index=True, default='available', max_length=20),
        ),
        migrations.AlterField(
            model_name='recordmovement',
            name='movement_type',
            field=models.CharField(choices=[('entry','Alta / importación'),('reserve','Reserva'),('loan','Préstamo'),('loan_return','Devolución préstamo'),('assign','Entrega / instalación'),('return','Devolución'),('scrap','Baja / merma'),('correction','Corrección')], max_length=20),
        ),
        migrations.CreateModel(
            name='Loan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('technician_name', models.CharField(db_index=True, max_length=160)),
                ('withdrawn_at', models.DateTimeField(db_index=True)),
                ('returned_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('borrower', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='inventory_loans_received', to=settings.AUTH_USER_MODEL)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='inventory_loans_created', to=settings.AUTH_USER_MODEL)),
                ('record', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='loans', to='inventory.inventoryrecord')),
                ('returned_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='inventory_loans_returned', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ('-withdrawn_at', '-pk'),
                'constraints': [models.UniqueConstraint(condition=models.Q(('returned_at__isnull', True)), fields=('record',), name='one_active_loan_per_record')],
            },
        ),
    ]
