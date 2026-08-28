from django.db import migrations, models
from django.conf import settings
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0016_access_schedule_security_policy'),
    ]

    operations = [
        migrations.CreateModel(
            name='SecurityAccessPolicy',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('enabled', models.BooleanField(default=False)),
                ('allowed_days', models.CharField(default='0,1,2,3,4', max_length=32)),
                ('start_time', models.TimeField(default='08:00')),
                ('end_time', models.TimeField(default='18:00')),
                ('logout_before_end_seconds', models.PositiveIntegerField(default=60)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name='SecurityAccessEvent',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('level', models.CharField(max_length=10)),
                ('event_type', models.CharField(max_length=50)),
                ('description', models.CharField(max_length=500)),
                ('ip', models.GenericIPAddressField(null=True, blank=True)),
                ('reviewed', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='ActiveSecuritySession',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('session_key', models.CharField(max_length=100)),
                ('ip', models.GenericIPAddressField(null=True, blank=True)),
                ('user_agent', models.TextField(blank=True)),
                ('started_at', models.DateTimeField(auto_now_add=True)),
                ('last_activity', models.DateTimeField(auto_now=True)),
                ('closed', models.BooleanField(default=False)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
