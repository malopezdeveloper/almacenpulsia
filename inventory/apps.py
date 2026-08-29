import sys
from django.apps import AppConfig

class InventoryConfig(AppConfig):
 default_auto_field="django.db.models.BigAutoField"
 name="inventory"
 verbose_name="Inventario técnico"
 def ready(self):
  from . import order_models,responsibility_models
  original_save=order_models.OrderUnit.save
  def lifecycle_save(instance,*args,**kwargs):
   if not instance.physical_unit_id:
    defaults={'brand':instance.brand,'model':instance.model,'processor':instance.processor,'ram':instance.ram,'disk':instance.disk}
    physical,_=order_models.PhysicalUnit.objects.get_or_create(serial_number=instance.serial_number,defaults=defaults);instance.physical_unit=physical
   return original_save(instance,*args,**kwargs)
  order_models.OrderUnit.save=lifecycle_save
  # La URL histórica conserva su nombre, pero ahora importa un nuevo ciclo del mismo
  # equipo físico si el SN ya pasó por pedidos anteriores.
  if not any(arg in {'makemigrations','migrate'} for arg in sys.argv[1:2]):
   try:
    from . import order_views,order_lifecycle_views
    order_views.aiken_import=order_lifecycle_views.aiken_import_cycle
   except Exception:pass
  from .db_utils import install_sqlite_pragmas
  install_sqlite_pragmas()
  blocked={'makemigrations','migrate','collectstatic','test','check','shell','createsuperuser'}
  if any(arg in blocked for arg in sys.argv[1:2]):return
  try:
   from .backup_scheduler import start_scheduler
   start_scheduler()
  except Exception:pass