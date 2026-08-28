from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("inventory", "0011_clientbatchrow_brand_clientbatchrow_component_and_more")]
    operations = [
        migrations.AlterField(
            model_name="ipban",
            name="banned_until",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
