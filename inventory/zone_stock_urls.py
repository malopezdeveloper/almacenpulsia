from django.urls import path
from . import zone_stock_views

urlpatterns = [
    path('produccion/stock-zonas/', zone_stock_views.zone_stock, name='zone_stock'),
    path('produccion/intervencion/<int:intervention_pk>/terminar/', zone_stock_views.finish_unit_intervention, name='zone_stock_finish_unit_intervention'),
    path('produccion/intervencion/<int:intervention_pk>/borrar/', zone_stock_views.delete_unit_intervention, name='zone_stock_delete_unit_intervention'),
]
