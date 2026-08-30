from django.urls import include,path
from inventory import views,manager_delete_views
urlpatterns=[path("acceso-inicial/<str:token>/",views.gestor_bootstrap_login,name="gestor_bootstrap_login"),path("cuenta/login/",views.auto_register_login,name="login"),path("cuenta/",include("django.contrib.auth.urls")),path("pedidos/tabla/<str:kind>/<int:pk>/eliminar/",manager_delete_views.internal_delete,name="internal_delete"),path("",include("inventory.priority_urls")),path("",include("inventory.urls"))]
