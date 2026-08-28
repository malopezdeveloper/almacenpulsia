import hashlib
import json
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.sessions.models import Session
from django.utils import timezone

from .models import (
    ActiveSecuritySession,
    AuditLog,
    SecurityAccessEvent,
    SecurityAccessPolicy,
    UserProfile,
)


ACTIVE_WINDOW_MINUTES = 10


def get_policy():
    policy, _ = SecurityAccessPolicy.objects.get_or_create(pk=1)
    return policy


def _local_now(value=None):
    return timezone.localtime(value or timezone.now())


def _time_in_range(current, start, end):
    if start < end:
        return start <= current < end
    if start > end:
        return current >= start or current < end
    return False


def access_window_state(policy=None, when=None):
    """
    Returns:
      allowed: current instant is inside the configured access window.
      seconds_until_end: seconds to the end of the active window, or None.
      forced_logout: inside the active window and <= configured cutoff.
    Overnight windows are supported. A Monday 22:00-06:00 policy means
    Monday 22:00 through Tuesday 06:00.
    """
    policy = policy or get_policy()
    now = _local_now(when)
    if not policy.enabled:
        return {"allowed": True, "seconds_until_end": None, "forced_logout": False}

    allowed_days = policy.allowed_day_numbers
    current_time = now.time().replace(tzinfo=None)
    start = policy.start_time
    end = policy.end_time

    if start < end:
        allowed = now.weekday() in allowed_days and start <= current_time < end
        end_dt = timezone.make_aware(datetime.combine(now.date(), end), timezone.get_current_timezone()) if allowed else None
    elif start > end:
        # Before midnight belongs to current allowed day; after midnight belongs
        # to the previous allowed day.
        if current_time >= start and now.weekday() in allowed_days:
            allowed = True
            end_dt = timezone.make_aware(datetime.combine(now.date() + timedelta(days=1), end), timezone.get_current_timezone())
        else:
            previous_day = (now.weekday() - 1) % 7
            allowed = current_time < end and previous_day in allowed_days
            end_dt = timezone.make_aware(datetime.combine(now.date(), end), timezone.get_current_timezone()) if allowed else None
    else:
        allowed = False
        end_dt = None

    seconds = max(0, int((end_dt - now).total_seconds())) if end_dt else None
    cutoff = max(0, int(policy.logout_before_end_seconds or 60))
    forced = bool(allowed and seconds is not None and seconds <= cutoff)
    return {"allowed": allowed, "seconds_until_end": seconds, "forced_logout": forced}


def parse_user_agent(user_agent):
    ua=(user_agent or "")
    lower=ua.casefold()
    if "edg/" in lower: browser="Edge"
    elif "chrome/" in lower and "chromium" not in lower: browser="Chrome"
    elif "firefox/" in lower: browser="Firefox"
    elif "safari/" in lower and "chrome/" not in lower: browser="Safari"
    else: browser="Otro / desconocido"

    if "windows nt 10.0" in lower: os_name="Windows 10/11"
    elif "windows" in lower: os_name="Windows"
    elif "android" in lower: os_name="Android"
    elif "iphone" in lower or "ipad" in lower: os_name="iOS/iPadOS"
    elif "mac os x" in lower or "macintosh" in lower: os_name="macOS"
    elif "linux" in lower: os_name="Linux"
    else: os_name="Desconocido"
    return browser, os_name


def request_ip(request):
    remote=(request.META.get("REMOTE_ADDR") or "").strip()
    if remote in {"127.0.0.1","::1"}:
        forwarded=(request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
        if forwarded:
            return forwarded
    return remote or "0.0.0.0"


def _create_event_once(user, level, event_type, description, ip=None, previous_ip=None, previous_data=None, current_data=None, minutes=5):
    threshold=timezone.now()-timedelta(minutes=minutes)
    duplicate=SecurityAccessEvent.objects.filter(
        user=user,level=level,event_type=event_type,reviewed=False,created_at__gte=threshold,
        ip=ip or None,previous_ip=previous_ip or None,
    ).exists()
    if duplicate:
        return None
    event=SecurityAccessEvent.objects.create(
        user=user,level=level,event_type=event_type,description=description[:500],
        ip=ip or None,previous_ip=previous_ip or None,
        previous_data=previous_data or {},current_data=current_data or {},
    )
    AuditLog.objects.create(
        user=user,action=f"security_{event_type.lower()}",
        object_type="SecurityAccessEvent",object_id=str(event.pk),
        details={"level":level,"ip":ip,"previous_ip":previous_ip,"description":description[:500]},
    )
    return event


def block_out_of_schedule(user, request):
    if user.is_superuser:
        return
    now=timezone.now()
    ip=request_ip(request)
    profile,_=UserProfile.objects.get_or_create(user=user)
    user.is_active=False
    user.save(update_fields=["is_active"])
    profile.archived_at=now
    profile.archived_by=None
    profile.archived_reason="OUT_OF_SCHEDULE · Acceso fuera del horario permitido"
    profile.save(update_fields=["archived_at","archived_by","archived_reason","updated_at"])
    policy=get_policy()
    state=access_window_state(policy)
    _create_event_once(
        user,"RED","OUT_OF_SCHEDULE",
        f"Intento de acceso fuera del horario permitido ({policy.start_time:%H:%M}-{policy.end_time:%H:%M}). Usuario bloqueado indefinidamente.",
        ip=ip,current_data={"path":request.path,"allowed_days":policy.allowed_days},
        minutes=1,
    )


def login_allowed(user, request):
    if user.is_superuser:
        return True
    policy=get_policy()
    if not policy.enabled:
        return True
    state=access_window_state(policy)
    if state["allowed"] and not state["forced_logout"]:
        return True
    block_out_of_schedule(user, request)
    return False


def _fingerprint_hash(data):
    payload=json.dumps(data,sort_keys=True,ensure_ascii=False,separators=(",",":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def register_login_session(user, request):
    if not request.session.session_key:
        request.session.save()
    key=request.session.session_key
    ip=request_ip(request)
    ua=(request.META.get("HTTP_USER_AGENT") or "")[:4000]
    browser, os_name=parse_user_agent(ua)
    now=timezone.now()

    # Mark stale security sessions closed.
    stale_before=now-timedelta(minutes=ACTIVE_WINDOW_MINUTES)
    ActiveSecuritySession.objects.filter(user=user,closed=False,last_activity__lt=stale_before).update(closed=True,closed_at=now)

    # Same user, another recently active IP => red alert, but never auto-block.
    other=ActiveSecuritySession.objects.filter(
        user=user,closed=False,last_activity__gte=stale_before
    ).exclude(session_key=key).exclude(ip=ip).order_by("-last_activity").first()
    if other:
        _create_event_once(
            user,"RED","MULTIPLE_IP",
            f"El mismo usuario mantiene actividad reciente desde dos IP diferentes: {other.ip} y {ip}.",
            ip=ip,previous_ip=other.ip,
            previous_data={"session_key":other.session_key,"user_agent":other.user_agent},
            current_data={"session_key":key,"user_agent":ua},
            minutes=5,
        )

    session, _=ActiveSecuritySession.objects.update_or_create(
        session_key=key,
        defaults={
            "user":user,"ip":ip,"user_agent":ua,"browser":browser,
            "operating_system":os_name,"closed":False,"closed_at":None,
        }
    )

    # Server-side yellow fingerprint check based on UA/browser/OS/IP change.
    previous=ActiveSecuritySession.objects.filter(user=user).exclude(pk=session.pk).order_by("-last_activity").first()
    if previous:
        changed=[]
        if previous.user_agent and previous.user_agent != ua: changed.append("navegador/User-Agent")
        if previous.operating_system and previous.operating_system != os_name: changed.append("sistema operativo")
        # IP changes that are not simultaneous remain yellow.
        if previous.ip and previous.ip != ip and not other: changed.append("IP")
        if changed:
            _create_event_once(
                user,"YELLOW","FINGERPRINT_CHANGED",
                "Cambio detectado en la huella de acceso: "+", ".join(changed)+".",
                ip=ip,previous_ip=previous.ip,
                previous_data={"browser":previous.browser,"os":previous.operating_system,"user_agent":previous.user_agent},
                current_data={"browser":browser,"os":os_name,"user_agent":ua},
                minutes=10,
            )
    return session


def update_active_session(user, request):
    key=request.session.session_key
    if not key:
        return
    now=timezone.now()
    ip=request_ip(request)
    ua=(request.META.get("HTTP_USER_AGENT") or "")[:4000]
    browser, os_name=parse_user_agent(ua)
    obj, created=ActiveSecuritySession.objects.get_or_create(
        session_key=key,
        defaults={"user":user,"ip":ip,"user_agent":ua,"browser":browser,"operating_system":os_name}
    )
    if not created:
        ActiveSecuritySession.objects.filter(pk=obj.pk).update(
            user=user,ip=ip,user_agent=ua,browser=browser,operating_system=os_name,
            last_activity=now,closed=False,closed_at=None,
        )


def close_security_session(session_key):
    if not session_key:
        return
    now=timezone.now()
    ActiveSecuritySession.objects.filter(session_key=session_key,closed=False).update(closed=True,closed_at=now)
    try:
        Session.objects.filter(session_key=session_key).delete()
    except Exception:
        pass


def register_client_fingerprint(user, request, payload):
    key=request.session.session_key
    if not key:
        request.session.save()
        key=request.session.session_key
    current=ActiveSecuritySession.objects.filter(session_key=key,user=user).first()
    if not current:
        current=register_login_session(user,request)

    data={
        "language":str(payload.get("language") or "")[:40],
        "timezone":str(payload.get("timezone") or "")[:80],
        "screen":str(payload.get("screen") or "")[:40],
        "platform":str(payload.get("platform") or "")[:120],
        "hardware_concurrency":payload.get("hardware_concurrency"),
        "device_memory":payload.get("device_memory"),
    }
    data={k:v for k,v in data.items() if v not in ("",None)}
    fp=_fingerprint_hash(data)

    previous=ActiveSecuritySession.objects.filter(user=user).exclude(pk=current.pk).exclude(fingerprint_hash="").order_by("-last_activity").first()
    if previous and previous.fingerprint_hash != fp:
        changed=[]
        old=previous.client_data or {}
        for key_name,label in (("language","idioma"),("timezone","zona horaria"),("screen","resolución"),("platform","plataforma"),("hardware_concurrency","CPU lógica"),("device_memory","memoria indicada por navegador")):
            if old.get(key_name) != data.get(key_name):
                changed.append(label)
        _create_event_once(
            user,"YELLOW","FINGERPRINT_CHANGED",
            "La información del cliente ha cambiado: "+(", ".join(changed) if changed else "huella del navegador")+".",
            ip=request_ip(request),previous_ip=previous.ip,
            previous_data=old,current_data=data,minutes=10,
        )

    ActiveSecuritySession.objects.filter(pk=current.pk).update(
        language=data.get("language",""),timezone_name=data.get("timezone",""),
        screen_resolution=data.get("screen",""),client_data=data,fingerprint_hash=fp,
        last_activity=timezone.now(),
    )


def seconds_until_logout_for_user(user):
    if not user or not user.is_authenticated or user.is_superuser:
        return None
    policy=get_policy()
    state=access_window_state(policy)
    if not policy.enabled:
        return None
    return state["seconds_until_end"] if state["allowed"] else 0
