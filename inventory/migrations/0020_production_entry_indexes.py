from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("inventory", "0019_production_entry")]
    operations = [
        migrations.AddIndex(
            model_name="productionentry",
            index=models.Index(fields=["date", "hour"], name="prod_date_hour_idx"),
        ),
        migrations.AddIndex(
            model_name="productionentry",
            index=models.Index(fields=["user", "date"], name="prod_user_date_idx"),
        ),
        migrations.AddIndex(
            model_name="productionentry",
            index=models.Index(fields=["zone", "date"], name="prod_zone_date_idx"),
        ),
    ]
