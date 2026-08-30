from django.urls import path
from . import priority_views

urlpatterns = [
    path('produccion/prioridades/', priority_views.priority_panel, name='board_priorities'),
    path('produccion/prioridades/<int:pk>/retirar/', priority_views.priority_disable, name='board_priority_disable'),
    path('pedidos/unidad/<int:unit_pk>/a-stock/', priority_views.move_unit_to_stock, name='move_unit_to_stock'),
]
