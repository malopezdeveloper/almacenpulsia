import sys
from django.apps import AppConfig

class InventoryConfig(AppConfig):
 default_auto_field="django.db.models.BigAutoField"
 name="inventory"
 verbose_name="Inventario técnico"

 def ready(self):
  from . import order_models
  from .db_utils import install_sqlite_pragmas
  install_sqlite_pragmas()
  blocked={"makemigrations","migrate","collectstatic","test","check","shell","createsuperuser"}
  if any(arg in blocked for arg in sys.argv[1:2]): return
  try:
   from .backup_scheduler import start_scheduler
   start_scheduler()
  except Exception: pass
