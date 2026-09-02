import os
import subprocess
import threading
import time
from pathlib import Path

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

_started=False
_lock=threading.Lock()


def execute_backup(schedule=None):
    from .models import BackupSchedule
    schedule=schedule or BackupSchedule.objects.first()
    if not schedule:
        raise ValueError("No existe configuración de backup.")
    db=settings.DATABASES["default"]
    if db["ENGINE"]!="django.db.backends.postgresql":
        raise ValueError("PostgreSQL es obligatorio para las copias de PULSIA.")
    destination=Path((schedule.destination or "").strip()).expanduser()
    if not str(destination):
        raise ValueError("Debe configurar un destino para las copias.")
    destination.mkdir(parents=True,exist_ok=True)
    probe=destination/".pulsia_write_test"
    probe.write_text("ok",encoding="utf-8"); probe.unlink(missing_ok=True)
    stamp=timezone.localtime().strftime("%Y%m%d_%H%M%S")
    target=destination/f"inventario_{stamp}.pgdump"
    env=os.environ.copy()
    if db.get("PASSWORD"):
        env["PGPASSWORD"]=str(db["PASSWORD"])
    cmd=["pg_dump","--format=custom","--no-owner","--no-privileges","--file",str(target)]
    if db.get("HOST"): cmd += ["--host",str(db["HOST"])]
    if db.get("PORT"): cmd += ["--port",str(db["PORT"])]
    if db.get("USER"): cmd += ["--username",str(db["USER"])]
    cmd.append(str(db["NAME"]))
    try:
        subprocess.run(cmd,env=env,check=True,capture_output=True,text=True)
    except FileNotFoundError as exc:
        raise ValueError("pg_dump no está instalado.") from exc
    except subprocess.CalledProcessError as exc:
        target.unlink(missing_ok=True)
        raise ValueError((exc.stderr or "Error creando backup PostgreSQL").strip()) from exc
    retention=max(1,min(int(schedule.retention or 30),1000))
    backups=sorted(destination.glob("inventario_*.pgdump"),key=lambda p:p.stat().st_mtime,reverse=True)
    for old in backups[retention:]:
        try: old.unlink()
        except OSError: pass
    schedule.last_run_at=timezone.now(); schedule.last_status="ok"; schedule.last_error=""
    schedule.save(update_fields=["last_run_at","last_status","last_error","updated_at"])
    return target


def _run_due_backup():
    from .models import BackupSchedule
    schedule=BackupSchedule.objects.first()
    if not schedule or not schedule.enabled or not schedule.destination: return
    now=timezone.localtime(); due_today=now.time().replace(tzinfo=None)>=schedule.run_time
    last_local=timezone.localtime(schedule.last_run_at) if schedule.last_run_at else None
    already_today=bool(last_local and last_local.date()==now.date())
    if due_today and not already_today:
        try: execute_backup(schedule)
        except Exception as exc:
            schedule.last_run_at=timezone.now(); schedule.last_status="error"; schedule.last_error=str(exc)[:4000]
            schedule.save(update_fields=["last_run_at","last_status","last_error","updated_at"])


def _loop():
    while True:
        try: close_old_connections(); _run_due_backup()
        except Exception: pass
        finally: close_old_connections()
        time.sleep(30)


def start_scheduler():
    global _started
    with _lock:
        if _started: return
        _started=True
        threading.Thread(target=_loop,name="pulsia-backup-scheduler",daemon=True).start()
