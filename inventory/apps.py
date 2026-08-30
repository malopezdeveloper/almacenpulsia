from django.apps import AppConfig

class InventoryConfig(AppConfig):
 default_auto_field="django.db.models.BigAutoField"
 name="inventory"
 verbose_name="Inventario técnico"
 def ready(self):
  # Importar los módulos de modelos del dominio para que Django los registre.
  from . import order_models,responsibility_models,component_flow_models,unit_workflow_models,priority_models
  # La columna customer admite NULL exclusivamente para el pedido técnico STOCK.
  # 0041 ya hizo nullable la columna física; alineamos aquí el metadato runtime
  # para que select_related('customer') use LEFT OUTER JOIN y no oculte STOCK.
  order_models.CustomerOrder._meta.get_field('customer').null=True
  order_models.CustomerOrder._meta.get_field('customer').blank=True
  from .db_utils import install_sqlite_pragmas
  install_sqlite_pragmas()
  try:
   from .backup_scheduler import start_scheduler
   start_scheduler()
  except Exception:
   # El scheduler nunca debe impedir arrancar la aplicación; su estado se revisa
   # desde el centro de backups.
   pass
