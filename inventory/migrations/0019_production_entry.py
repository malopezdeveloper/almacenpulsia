from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings
import datetime

class Migration(migrations.Migration):
    dependencies=[('inventory','0018_security_runtime_complete')]
    operations=[
        migrations.CreateModel(
            name='ProductionEntry',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('date',models.DateField(default=datetime.date.today,db_index=True)),
                ('hour',models.PositiveSmallIntegerField(default=0)),
                ('model_name',models.CharField(max_length=120)),
                ('zone',models.CharField(max_length=30)),
                ('quantity',models.PositiveIntegerField(default=1)),
                ('created_at',models.DateTimeField(auto_now_add=True)),
                ('user',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering':['-created_at']}
        )
    ]
