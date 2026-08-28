#!/usr/bin/env python3
import json, os, sqlite3, subprocess, time
from datetime import datetime, timezone
from pathlib import Path
CONFIG=Path("/var/lib/pulsia-inventario/backup-disk.json")
STATUS=Path("/var/lib/pulsia-inventario/continuous-backup/status.json")
MOUNT=Path("/mnt/pulsia-backup")
SOURCE=Path(os.environ.get("PULSIA_DB_PATH",""))
INTERVAL=float(os.environ.get("PULSIA_CONTINUOUS_BACKUP_INTERVAL","1.0"))

def write_status(**kw):
    STATUS.parent.mkdir(parents=True,exist_ok=True)
    base={"updated_at":datetime.now(timezone.utc).isoformat(),**kw}
    tmp=STATUS.with_suffix('.tmp'); tmp.write_text(json.dumps(base,ensure_ascii=False),encoding='utf-8'); os.replace(tmp,STATUS)

def mounted_uuid():
    p=subprocess.run(["findmnt","-nro","UUID",str(MOUNT)],text=True,capture_output=True)
    return p.stdout.strip() if p.returncode==0 else ""

def fingerprint():
    out=[]
    for p in (SOURCE,Path(str(SOURCE)+"-wal"),Path(str(SOURCE)+"-shm")):
        try:
            s=p.stat(); out.append((str(p),s.st_mtime_ns,s.st_size))
        except FileNotFoundError: out.append((str(p),0,0))
    return tuple(out)

def backup(target_root):
    target_dir=Path(target_root)/"continuo"; target_dir.mkdir(parents=True,exist_ok=True)
    target=target_dir/"inventario.sqlite3"; tmp=target_dir/f".inventario.sqlite3.tmp-{os.getpid()}"
    try: tmp.unlink(missing_ok=True)
    except Exception: pass
    src=sqlite3.connect(str(SOURCE),timeout=10); dst=sqlite3.connect(str(tmp),timeout=10)
    try:
        src.backup(dst)
        chk=dst.execute("PRAGMA quick_check").fetchone()[0]
        if chk!="ok": raise RuntimeError("quick_check: "+str(chk))
    finally:
        dst.close(); src.close()
    os.replace(tmp,target)
    return target

def main():
    last=None; last_ok=None
    while True:
        try:
            if not CONFIG.exists(): write_status(state='unconfigured',message='No hay destino de copia continua configurado.'); time.sleep(INTERVAL); continue
            cfg=json.loads(CONFIG.read_text(encoding='utf-8')); mode=cfg.get('mode','disk'); uuid=cfg.get('uuid','')
            if mode=='local':
                local_raw=(cfg.get('local_path') or '').strip()
                if not local_raw: write_status(state="unconfigured",mode="local",message="No hay directorio local configurado."); time.sleep(INTERVAL); continue
                target_root=Path(local_raw)
                try:
                    target_root.mkdir(parents=True,exist_ok=True)
                    probe=target_root/".pulsia-write-test"; probe.write_text("ok",encoding="utf-8"); probe.unlink(missing_ok=True)
                except Exception as exc:
                    write_status(state="error",mode="local",target_root=str(target_root),message="El directorio local no es escribible: "+str(exc),last_backup_at=last_ok); last=None; time.sleep(INTERVAL); continue
                expected_info={"mode":"local","target_root":str(target_root)}
            else:
                if not uuid: write_status(state="unconfigured",mode="disk",message="No hay disco fijo configurado."); time.sleep(INTERVAL); continue
                mu=mounted_uuid(); uuid_path=Path("/dev/disk/by-uuid")/uuid
                if not uuid_path.exists() or mu!=uuid:
                    write_status(state="missing",mode="disk",expected_uuid=uuid,mounted_uuid=mu,message="El disco fijo de backup no está disponible.",last_backup_at=last_ok)
                    last=None; time.sleep(INTERVAL); continue
                try: MOUNT.stat()
                except OSError as exc:
                    write_status(state="missing",mode="disk",expected_uuid=uuid,mounted_uuid=mu,message="El disco fijo no responde: "+str(exc),last_backup_at=last_ok); last=None; time.sleep(INTERVAL); continue
                target_root=MOUNT; expected_info={"mode":"disk","expected_uuid":uuid}
            if not SOURCE.exists():
                write_status(state="error",expected_uuid=uuid,message="No existe la base SQLite origen.",last_backup_at=last_ok); time.sleep(INTERVAL); continue
            fp=fingerprint()
            target=Path(target_root)/"continuo"/"inventario.sqlite3"
            if fp!=last or not target.exists():
                time.sleep(0.15)
                target=backup(target_root); last=fingerprint(); last_ok=datetime.now(timezone.utc).isoformat()
                write_status(state="ok",last_backup_at=last_ok,target=str(target),message="Copia continua sincronizada.",**expected_info)
            else:
                write_status(state="ok",last_backup_at=last_ok,target=str(target),message="Sin cambios pendientes.",**expected_info)
        except Exception as exc:
            write_status(state="error",message=str(exc),last_backup_at=last_ok)
            last=None
        time.sleep(INTERVAL)
if __name__=="__main__": main()
