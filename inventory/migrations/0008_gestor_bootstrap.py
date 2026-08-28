from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("inventory", "0007_loans_password_reset_and_statuses")]
    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="bootstrap_token_hash",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="bootstrap_expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="bootstrap_used_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
