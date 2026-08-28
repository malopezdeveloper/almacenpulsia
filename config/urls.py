from django.urls import include,path
from inventory import views
urlpatterns=[path("acceso-inicial/<str:token>/",views.gestor_bootstrap_login,name="gestor_bootstrap_login"),path("cuenta/login/",views.auto_register_login,name="login"),path("cuenta/",include("django.contrib.auth.urls")),path("",include("inventory.urls"))]
