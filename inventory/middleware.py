from datetime import timedelta
from django.http import Http404, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect
from django.contrib.auth import logout
from django.db.models import F, Q
from django.utils import timezone
from .models import UserProfile, ServiceAccess, IPBan, SecurityAccessEvent
from .ip_utils import is_protected_local_ip
from .security import access_window_state, close_security_session, get_policy, update_active_session
from pathlib import Path
from django.conf import settings


class MaintenanceModeMiddleware:
 def __init__(self,get_response): self.get_response=get_response
 def __call__(self,request):
  marker=Path(settings.BASE_DIR)/"data"/".maintenance"
  if marker.exists() and not request.path.startswith(("/static/","/health/")):
   return HttpResponse("PULSIA Almacén está realizando una operación de mantenimiento. Reintente en unos segundos.",status=503,content_type="text/plain; charset=utf-8")
  return self.get_response(request)

class AccountSecurityMiddleware:
 def __init__(self,get_response): self.get_response=get_response
 def __call__(self,request):
  if request.user.is_authenticated:
   profile,_=UserProfile.objects.get_or_create(user=request.user)
   allowed=("/cuenta/cambiar-clave/","/cuenta/logout/","/static/")
   if profile.must_change_password and not request.path.startswith(allowed): return redirect("change_required_password")
  return self.get_response(request)


class SecurityRuntimeMiddleware:
 """
 Seguridad en tiempo real para sesiones ya autenticadas.
 - Gestor/superuser queda totalmente exento.
 - Actualiza la actividad de la sesión.
 - Dentro de los últimos N segundos del horario, fuerza el cierre.
 - Fuera de horario, una sesión antigua que intente reutilizarse se cierra.
 El bloqueo indefinido se aplica al intentar LOGIN fuera de horario.
 """
 def __init__(self,get_response): self.get_response=get_response
 def __call__(self,request):
  user=getattr(request,"user",None)
  if user and user.is_authenticated:
   current_key=request.session.session_key
   if request.path.startswith("/cuenta/logout/"):
    close_security_session(current_key)
    return self.get_response(request)

   if not user.is_superuser:
    try:
     policy=get_policy()
     if policy.enabled:
      state=access_window_state(policy)
      if state["forced_logout"] or not state["allowed"]:
       # Registrar una sola vez por ventana corta.
       if not SecurityAccessEvent.objects.filter(
        user=user,event_type="AUTO_LOGOUT",reviewed=False,
        created_at__gte=timezone.now()-timedelta(minutes=2)
       ).exists():
        SecurityAccessEvent.objects.create(
         user=user,level="YELLOW",event_type="AUTO_LOGOUT",
         description="Sesión cerrada automáticamente por límite de horario.",
         ip=(request.META.get("HTTP_X_FORWARDED_FOR") or request.META.get("REMOTE_ADDR") or "").split(",")[0].strip() or None,
         current_data={"path":request.path,"seconds_until_end":state.get("seconds_until_end")},
        )
       close_security_session(current_key)
       logout(request)
       if request.path.startswith("/seguridad/estado-sesion/") or request.headers.get("x-requested-with")=="XMLHttpRequest":
        return JsonResponse({"force_logout":True,"reason":"Horario finalizado"},status=401)
       return redirect("login")
    except Exception:
     # No romper la aplicación si todavía no se han aplicado las migraciones.
     pass
   try:
    update_active_session(user,request)
   except Exception:
    pass
  return self.get_response(request)

class GuestAccessMiddleware:
 def __init__(self,get_response): self.get_response=get_response
 def __call__(self,request):
  user=getattr(request,"user",None)
  if user and user.is_authenticated and not user.is_staff and not user.is_superuser:
   profile,_=UserProfile.objects.get_or_create(user=user)
   if profile.is_guest:
    path=request.path or "/"
    allowed_exact={"/","/cuenta/solicitar-acceso/","/notificaciones/estado/","/cuenta/cambiar-clave/","/cuenta/logout/","/seguridad/huella/","/seguridad/estado-sesion/","/seguridad/certificado/","/seguridad/certificado/descargar/"}
    allowed_prefixes=("/chat/","/static/")
    if path not in allowed_exact and not path.startswith(allowed_prefixes):
     return redirect("dashboard")
  return self.get_response(request)

class InternalPathBlockMiddleware:
 blocked_prefixes=("/.git","/.env","/data","/backups","/logs","/sistema","/config","/inventory","/manage.py","/requirements")
 blocked_suffixes=(".sqlite3",".sqlite",".db",".env",".log",".ps1",".sh",".py")
 def __init__(self,get_response): self.get_response=get_response
 def __call__(self,request):
  path=request.path.lower()
  if path.startswith(self.blocked_prefixes) or path.endswith(self.blocked_suffixes): raise Http404
  response=self.get_response(request)
  response["X-Robots-Tag"]="noindex, nofollow, noarchive"
  if not path.startswith("/static/"): response["Cache-Control"]="no-store"
  return response


def trusted_client_ip(request):
 remote=(request.META.get("REMOTE_ADDR") or "").strip()
 if remote in {"127.0.0.1","::1"}:
  forwarded=(request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
  if forwarded: return forwarded
 return remote or "0.0.0.0"

class AccessControlMiddleware:
 def __init__(self,get_response): self.get_response=get_response
 def __call__(self,request):
  path=request.path or "/"
  if path.startswith("/static/"):
   return self.get_response(request)
  ip=trusted_client_ip(request)
  now=timezone.now()
  active_ban=None
  if not is_protected_local_ip(ip):
   active_ban=IPBan.objects.filter(ip_address=ip,revoked_at__isnull=True).filter(Q(banned_until__isnull=True)|Q(banned_until__gt=now)).order_by(F("banned_until").desc(nulls_first=True),"-banned_at").first()
  if active_ban:
   return HttpResponseForbidden("Acceso bloqueado permanentemente por el Gestor." if active_ban.banned_until is None else f"Acceso temporalmente bloqueado hasta {active_ban.banned_until:%d/%m/%Y %H:%M}.")
  user=request.user if getattr(request,"user",None) and request.user.is_authenticated else None
  try:
   access,created=ServiceAccess.objects.get_or_create(ip_address=ip,user=user,defaults={"last_path":path[:500],"last_user_agent":request.META.get("HTTP_USER_AGENT","")[:500]})
   if not created:
    ServiceAccess.objects.filter(pk=access.pk).update(request_count=F("request_count")+1,last_seen_at=now,last_path=path[:500],last_user_agent=request.META.get("HTTP_USER_AGENT","")[:500])
  except Exception:
   pass
  return self.get_response(request)
