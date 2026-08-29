from pathlib import Path
import os
BASE_DIR=Path(__file__).resolve().parent.parent
from dotenv import load_dotenv
load_dotenv(BASE_DIR/".env")
DEBUG=os.getenv("DJANGO_DEBUG","false").lower()=="true"
SECRET_KEY=os.getenv("DJANGO_SECRET_KEY","").strip()
if not SECRET_KEY:
 if DEBUG:SECRET_KEY="solo-desarrollo-cambiar"
 else:raise RuntimeError("DJANGO_SECRET_KEY es obligatorio cuando DJANGO_DEBUG=false. Se cancela el arranque para evitar una instalación insegura.")
ALLOWED_HOSTS=[x.strip() for x in os.getenv("DJANGO_ALLOWED_HOSTS","localhost,127.0.0.1").split(",")]
INSTALLED_APPS=["django.contrib.admin","django.contrib.auth","django.contrib.contenttypes","django.contrib.sessions","django.contrib.messages","django.contrib.staticfiles","inventory"]
MIDDLEWARE=["django.middleware.security.SecurityMiddleware","inventory.middleware.InternalPathBlockMiddleware","inventory.middleware.MaintenanceModeMiddleware","whitenoise.middleware.WhiteNoiseMiddleware","django.contrib.sessions.middleware.SessionMiddleware","django.middleware.common.CommonMiddleware","django.middleware.csrf.CsrfViewMiddleware","django.contrib.auth.middleware.AuthenticationMiddleware","inventory.middleware.SecurityRuntimeMiddleware","inventory.middleware.AccessControlMiddleware","inventory.middleware.AccountSecurityMiddleware","inventory.middleware.GuestAccessMiddleware","django.contrib.messages.middleware.MessageMiddleware","django.middleware.clickjacking.XFrameOptionsMiddleware"]
ROOT_URLCONF="config.urls"
TEMPLATES=[{"BACKEND":"django.template.backends.django.DjangoTemplates","DIRS":[],"APP_DIRS":True,"OPTIONS":{"context_processors":["django.template.context_processors.request","django.contrib.auth.context_processors.auth","django.contrib.messages.context_processors.messages","inventory.context_processors.inventory_navigation"]}}]
WSGI_APPLICATION="config.wsgi.application"
db=os.getenv("DATABASE_URL","sqlite:///data/inventario.sqlite3")
if db.startswith("postgresql://"):
 from urllib.parse import urlparse
 u=urlparse(db);DATABASES={"default":{"ENGINE":"django.db.backends.postgresql","NAME":u.path[1:],"USER":u.username,"PASSWORD":u.password,"HOST":u.hostname,"PORT":u.port or 5432,"OPTIONS":{"connect_timeout":10}}}
else:DATABASES={"default":{"ENGINE":"django.db.backends.sqlite3","NAME":BASE_DIR/"data"/"inventario.sqlite3","OPTIONS":{"timeout":10}}}
AUTH_PASSWORD_VALIDATORS=[{"NAME":"django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},{"NAME":"django.contrib.auth.password_validation.MinimumLengthValidator","OPTIONS":{"min_length":8}},{"NAME":"django.contrib.auth.password_validation.CommonPasswordValidator"}]
LANGUAGE_CODE="es-es";TIME_ZONE="Europe/Madrid";USE_I18N=True;USE_TZ=True
STATIC_URL="static/";STATIC_ROOT=BASE_DIR/"staticfiles";DEFAULT_AUTO_FIELD="django.db.models.BigAutoField"
LOGIN_URL="login";LOGIN_REDIRECT_URL="dashboard";LOGOUT_REDIRECT_URL="login"
SESSION_COOKIE_HTTPONLY=True;CSRF_COOKIE_HTTPONLY=True;SECURE_CONTENT_TYPE_NOSNIFF=True;X_FRAME_OPTIONS="DENY";SECURE_REFERRER_POLICY="same-origin"
# Evita que una petición enorme se materialice accidentalmente en memoria. Los ficheros
# mayores pasan a almacenamiento temporal del sistema; los importadores deben procesarlos por streaming.
DATA_UPLOAD_MAX_MEMORY_SIZE=16*1024*1024;FILE_UPLOAD_MAX_MEMORY_SIZE=2*1024*1024
SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO","https")
SESSION_COOKIE_SECURE=os.getenv("DJANGO_HTTPS","false").lower()=="true";CSRF_COOKIE_SECURE=SESSION_COOKIE_SECURE
SECURE_SSL_REDIRECT=False
CSRF_TRUSTED_ORIGINS=[x.strip() for x in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS","https://almacen,https://pizarra").split(",") if x.strip()]
CSRF_COOKIE_SAMESITE="Lax";SESSION_COOKIE_SAMESITE="Lax"
