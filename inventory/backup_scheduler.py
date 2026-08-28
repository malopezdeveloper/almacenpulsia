import os
import sqlite3
import threading
import time
from pathlib import Path

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone
from .db_utils import create_sqlite_snapshot

_started=False
_lock=threading.Lock()


def execute_backup(schedule=None):
    from .models import BackupSchedule
    schedule=schedule or BackupSchedule.objects.first()
    if not schedule:
        raise ValueError("No existe configuración de backup.")
    db=settings.DATABASES["default"]
    if db["ENGINE"]!="django.db.backends.sqlite3":
        raise ValueError("El backup automático interno está disponible únicamente para SQLite.")
    destination=Path((schedule.destination or "").strip()).expanduser()
    if not destination:
        raise ValueError("Debe configurar un destino para las copias.")
    destination.mkdir(parents=True,exist_ok=True)
    probe=destination/".pulsia_write_test"
    probe.write_text("ok",encoding="utf-8")
    probe.unlink(missing_ok=True)

    source_path=Path(db["NAME"])
    stamp=timezone.localtime().strftime("%Y%m%d_%H%M%S")
    target=destination/f"inventario_{stamp}.sqlite3"
    create_sqlite_snapshot(source_path,target)

    retention=max(1,min(int(schedule.retention or 30),1000))
    backups=sorted(destination.glob("inventario_*.sqlite3"),key=lambda p:p.stat().st_mtime,reverse=True)
    for old in backups[retention:]:
        try:
            old.unlink()
        except OSError:
            pass

    schedule.last_run_at=timezone.now()
    schedule.last_status="ok"
    schedule.last_error=""
    schedule.save(update_fields=["last_run_at","last_status","last_error","updated_at"])
    return target


def _run_due_backup():
    from .models import BackupSchedule
    schedule=BackupSchedule.objects.first()
    if not schedule or not schedule.enabled or not schedule.destination:
        return
    now=timezone.localtime()
    due_today=now.time().replace(tzinfo=None)>=schedule.run_time
    last_local=timezone.localtime(schedule.last_run_at) if schedule.last_run_at else None
    already_today=bool(last_local and last_local.date()==now.date())
    if due_today and not already_today:
        try:
            execute_backup(schedule)
        except Exception as exc:
            schedule.last_run_at=timezone.now()
            schedule.last_status="error"
            schedule.last_error=str(exc)[:4000]
            schedule.save(update_fields=["last_run_at","last_status","last_error","updated_at"])


def _loop():
    while True:
        try:
            close_old_connections()
            _run_due_backup()
        except Exception:
            pass
        finally:
            close_old_connections()
        time.sleep(30)


def start_scheduler():
    global _started
    with _lock:
        if _started:
            return
        _started=True
        thread=threading.Thread(target=_loop,name="pulsia-backup-scheduler",daemon=True)
        thread.start()
