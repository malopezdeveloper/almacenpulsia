from django.urls import path
from . import pallet_views

urlpatterns = [
    path('pedidos/palets/', pallet_views.pallet_center, name='pallet_center'),
    path('pedidos/palets/abiertos/', pallet_views.open_pallets_api, name='open_pallets_api'),
    path('pedidos/palets/crear/', pallet_views.create_pallet, name='pallet_create'),
    path('pedidos/palets/intervencion/<int:intervention_pk>/anadir/', pallet_views.add_intervention_to_pallet, name='pallet_add_intervention'),
    path('pedidos/palets/unidad/<int:membership_pk>/retirar/', pallet_views.remove_unit_from_pallet, name='pallet_remove_unit'),
    path('pedidos/palets/<int:pallet_pk>/enviar/', pallet_views.ship_pallet, name='pallet_ship'),
]
