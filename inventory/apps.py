import sys
from django.apps import AppConfig

class InventoryConfig(AppConfig):
 default_auto_field="django.db.models.BigAutoField"
 name="inventory"
 verbose_name="Inventario técnico"
 def ready(self):
  # Importar los módulos de modelos del dominio para que Django los registre.
  # La lógica de ciclo de vida vive ahora en los modelos/vistas, no en monkey-patches.
  from . import order_models,responsibility_models,component_flow_models,unit_workflow_models,priority_models
  from .db_utils import install_sqlite_pragmas
  install_sqlite_pragmas()
  blocked={'makemigrations','migrate','collectstatic','test','check','shell','createsuperuser'}
  if any(arg in blocked for arg in sys.argv[1:2]):return
  try:
   from .backup_scheduler import start_scheduler
   start_scheduler()
  except Exception:
   # El scheduler nunca debe impedir arrancar la aplicación; su estado se revisa
   # desde el centro de backups.
   pass
