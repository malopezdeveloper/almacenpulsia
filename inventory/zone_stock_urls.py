from django.urls import path
from . import zone_stock_views, installation_confirmation_views

urlpatterns = [
    path('produccion/stock-zonas/', zone_stock_views.zone_stock, name='zone_stock'),
    path('produccion/intervencion/<int:intervention_pk>/terminar/', zone_stock_views.finish_unit_intervention, name='zone_stock_finish_unit_intervention'),
    path('produccion/intervencion/<int:intervention_pk>/borrar/', zone_stock_views.delete_unit_intervention, name='zone_stock_delete_unit_intervention'),
    # Ruta prioritaria: permite que el técnico confirme una pieza instalada
    # incluso si la intervención ya fue finalizada.
    path('produccion/intervencion/<int:intervention_pk>/reserva/<int:reservation_pk>/confirmar/', installation_confirmation_views.confirm_installation, name='workflow_confirm_repair'),
]
