from django.db import migrations

PERMISSIONS=['orders.view','orders.manage','customers.manage','suppliers.manage','components.manage','repairs.manage','components.reserve','rma.manage','procurement.view','procurement.resolve']

def seed(apps,schema_editor):
    Role=apps.get_model('inventory','BusinessRole')
    Role.objects.update_or_create(code='desarrollador',defaults={'name':'Desarrollador','permissions':PERMISSIONS,'active':True,'protected':True})

def unseed(apps,schema_editor):
    Role=apps.get_model('inventory','BusinessRole')
    Role.objects.filter(code='desarrollador').delete()

class Migration(migrations.Migration):
    dependencies=[('inventory','0031_area_responsibilities')]
    operations=[migrations.RunPython(seed,unseed)]