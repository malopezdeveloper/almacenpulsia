#!/usr/bin/env python3
import grp, json, os, re, shutil, socket, subprocess, time
from pathlib import Path

SOCKET="/run/pulsia-inventario/storage-admin.sock"
MOUNT_POINT=Path("/mnt/pulsia-backup")
FSTAB=Path("/etc/fstab")
MARKER="x-pulsia-backup"
CONFIG=Path("/var/lib/pulsia-inventario/backup-disk.json")
CONTINUOUS_SERVICE="pulsia-inventario-continuous-backup.service"
APP_USER=os.environ.get("PULSIA_APP_USER", "root")
APP_GROUP=os.environ.get("PULSIA_APP_GROUP", APP_USER)
ALLOWED_FS={"ext4","xfs","btrfs"}

def run(args, check=True):
    return subprocess.run(args,text=True,capture_output=True,check=check)

def value(args):
    p=run(args,check=False)
    return p.stdout.strip() if p.returncode==0 else ""

def root_source(): return os.path.realpath(value(["findmnt","-nro","SOURCE","/"]) or "")

def lsblk_tree():
    p=run(["lsblk","-J","-b","-o","NAME,PATH,TYPE,SIZE,MODEL,SERIAL,TRAN,FSTYPE,UUID,MOUNTPOINTS"],check=False)
    if p.returncode: raise ValueError((p.stderr or "No se pudo consultar lsblk").strip())
    data=json.loads(p.stdout or "{}")
    rs=root_source()
    def decorate(n,parent=None):
        path=n.get("path") or ("/dev/"+str(n.get("name") or ""))
        mounts=n.get("mountpoints") or []
        if isinstance(mounts,str): mounts=[mounts]
        mounts=[x for x in mounts if x]
        children=[decorate(c,n) for c in (n.get("children") or [])]
        contains_root=(os.path.realpath(path)==rs) or "/" in mounts or any(c.get("contains_root") for c in children)
        fstype=n.get("fstype") or ""; uuid=n.get("uuid") or ""; typ=n.get("type") or ""
        existing_target=value(["findmnt","-nro","TARGET","-S",path]) if typ in {"part","lvm","crypt"} else ""
        selectable=typ in {"part","lvm","crypt"} and bool(uuid) and fstype in ALLOWED_FS and not contains_root and (not existing_target or existing_target==str(MOUNT_POINT))
        return {"name":n.get("name") or "","path":path,"type":typ,"size":int(n.get("size") or 0),"model":(n.get("model") or "").strip(),"serial":(n.get("serial") or "").strip(),"transport":(n.get("tran") or "").strip(),"filesystem":fstype,"uuid":uuid,"mountpoints":mounts,"selectable":selectable,"contains_root":contains_root,"children":children}
    return [decorate(x) for x in data.get("blockdevices",[])]

def safe_device(raw):
    if not isinstance(raw,str) or not re.fullmatch(r"/dev/[A-Za-z0-9._/+:-]+",raw): raise ValueError("Dispositivo no válido.")
    real=os.path.realpath(raw)
    if not real.startswith("/dev/") or not os.path.exists(real): raise ValueError("El dispositivo indicado no existe.")
    if value(["lsblk","-dnro","TYPE",real]) not in {"part","lvm","crypt"}: raise ValueError("Seleccione una partición/volumen con sistema de archivos.")
    return real

def write_config(device,uuid,fstype,mode="disk",local_path=""):
    CONFIG.parent.mkdir(parents=True,exist_ok=True)
    CONFIG.write_text(json.dumps({"mode":mode,"local_path":local_path,"device":device,"uuid":uuid,"filesystem":fstype,"mount_point":str(MOUNT_POINT)},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    try:
        gid=grp.getgrnam(APP_GROUP).gr_gid
        os.chown(CONFIG,0,gid); os.chmod(CONFIG,0o640)
    except Exception: os.chmod(CONFIG,0o644)

def configure(device):
    device=safe_device(device)
    uuid=value(["blkid","-s","UUID","-o","value",device]); fstype=value(["blkid","-s","TYPE","-o","value",device])
    if not uuid or not fstype: raise ValueError("La partición no tiene UUID/sistema de archivos. PULSIA no formatea discos automáticamente.")
    if fstype not in ALLOWED_FS: raise ValueError(f"Sistema de archivos {fstype!r} no permitido. Use ext4, xfs o btrfs.")
    if root_source()==device: raise ValueError("La partición raíz del sistema no puede seleccionarse como backup.")
    current=value(["findmnt","-nro","SOURCE",str(MOUNT_POINT)])
    if current and os.path.realpath(current)!=device:
        run(["systemctl","stop",CONTINUOUS_SERVICE],check=False)
        mount_unit=value(["systemd-escape","-p","--suffix=mount",str(MOUNT_POINT)])
        u=run(["systemctl","stop",mount_unit],check=False) if mount_unit else run(["false"],check=False)
        if value(["findmnt","-nro","SOURCE",str(MOUNT_POINT)]): raise ValueError("No se pudo desmontar el disco de backup anterior mediante systemd: "+(u.stderr or u.stdout).strip())
        current=""
    existing=value(["findmnt","-nro","TARGET","-S",device])
    if existing and existing!=str(MOUNT_POINT): raise ValueError(f"El dispositivo ya está montado en {existing}; no se modificará.")
    if MOUNT_POINT.is_symlink(): raise ValueError("El punto de montaje no puede ser un enlace simbólico.")
    MOUNT_POINT.mkdir(parents=True,exist_ok=True)
    if not current and not existing and any(MOUNT_POINT.iterdir()): raise ValueError(f"{MOUNT_POINT} contiene archivos y no está montado; operación bloqueada.")
    original=FSTAB.read_text(encoding="utf-8")
    lines=[ln for ln in original.splitlines() if MARKER not in ln]
    opts="defaults,nofail,x-systemd.device-timeout=5s,"+MARKER
    entry=f"UUID={uuid} {MOUNT_POINT} {fstype} {opts} 0 {'2' if fstype=='ext4' else '0'}"
    bd=Path("/var/lib/pulsia-inventario/fstab-backups"); bd.mkdir(parents=True,exist_ok=True)
    backup=bd/f"fstab-{time.strftime('%Y%m%d-%H%M%S')}"; shutil.copy2(FSTAB,backup)
    FSTAB.write_text("\n".join(lines).rstrip()+"\n"+entry+"\n",encoding="utf-8")
    verify=run(["findmnt","--verify","--tab-file",str(FSTAB)],check=False)
    if verify.returncode:
        shutil.copy2(backup,FSTAB); raise ValueError("La nueva configuración fstab no superó la validación: "+(verify.stderr or verify.stdout).strip())
    run(["systemctl","daemon-reload"],check=False)
    if not value(["findmnt","-nro","SOURCE",str(MOUNT_POINT)]):
        mount_unit=value(["systemd-escape","-p","--suffix=mount",str(MOUNT_POINT)])
        if not mount_unit:
            shutil.copy2(backup,FSTAB); run(["systemctl","daemon-reload"],check=False)
            raise ValueError("No se pudo calcular la unidad systemd del punto de montaje.")
        m=run(["systemctl","start",mount_unit],check=False)
        if m.returncode or not value(["findmnt","-nro","SOURCE",str(MOUNT_POINT)]):
            shutil.copy2(backup,FSTAB); run(["systemctl","daemon-reload"],check=False); run(["systemctl","stop",mount_unit],check=False)
            raise ValueError("No se pudo montar el disco mediante systemd; /etc/fstab fue restaurado: "+(m.stderr or m.stdout).strip())
    try:
        uid=__import__('pwd').getpwnam(APP_USER).pw_uid; gid=grp.getgrnam(APP_GROUP).gr_gid
        os.chown(MOUNT_POINT,uid,gid); os.chmod(MOUNT_POINT,0o750)
    except Exception: pass
    write_config(device,uuid,fstype,mode="disk")
    run(["systemctl","restart",CONTINUOUS_SERVICE],check=False)
    return {"device":device,"uuid":uuid,"filesystem":fstype,"mount_point":str(MOUNT_POINT),"source":value(["findmnt","-nro","SOURCE",str(MOUNT_POINT)]),"fstab_backup":str(backup)}

def configure_local(raw_path=""):
    allowed=[Path("/almacen/backups"),Path("/var/lib/pulsia-inventario/local-backup")]
    if raw_path:
        target=Path(raw_path).expanduser()
        if not target.is_absolute(): target=allowed[0]/target
        target=Path(os.path.abspath(str(target)))
        if not any(target==base or str(target).startswith(str(base)+os.sep) for base in allowed):
            raise ValueError("El backup local sólo puede ubicarse bajo /almacen/backups o /var/lib/pulsia-inventario/local-backup.")
    else:
        target=allowed[0]/"proteccion-continuada"
    target.mkdir(parents=True,exist_ok=True)
    uid=__import__('pwd').getpwnam(APP_USER).pw_uid; gid=grp.getgrnam(APP_GROUP).gr_gid
    os.chown(target,uid,gid); os.chmod(target,0o750)
    probe=target/".pulsia-write-test"
    try:
        probe.write_text("ok",encoding="utf-8"); probe.unlink(missing_ok=True)
    except Exception as exc: raise ValueError("No se puede escribir en el directorio local: "+str(exc))
    write_config("","","",mode="local",local_path=str(target))
    run(["systemctl","restart",CONTINUOUS_SERVICE],check=False)
    return {"mode":"local","local_path":str(target),"mount_point":""}

def status(expected_uuid=""):
    src=value(["findmnt","-nro","SOURCE",str(MOUNT_POINT)])
    mounted_uuid=value(["findmnt","-nro","UUID",str(MOUNT_POINT)]) if src else ""
    present=bool(expected_uuid and Path("/dev/disk/by-uuid",expected_uuid).exists()) if expected_uuid else bool(src)
    service=value(["systemctl","is-active",CONTINUOUS_SERVICE])
    status_file=Path("/var/lib/pulsia-inventario/continuous-backup/status.json")
    continuous={}
    try: continuous=json.loads(status_file.read_text(encoding="utf-8"))
    except Exception: pass
    cfg={}
    try: cfg=json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception: pass
    return {"mode":cfg.get("mode","disk"),"local_path":cfg.get("local_path",""),"mounted":bool(src),"source":src,"mount_point":str(MOUNT_POINT),"mounted_uuid":mounted_uuid,"expected_uuid":expected_uuid,"present":present,"matches":bool(expected_uuid and mounted_uuid==expected_uuid),"continuous_service":service,"continuous":continuous}

def handle(req):
    action=req.get("action")
    if action=="configure_backup_mount": return {"ok":True,**configure(req.get("device",""))}
    if action=="configure_local_backup": return {"ok":True,**configure_local(req.get("path","") or "")}
    if action=="status_backup_mount": return {"ok":True,**status(req.get("uuid","") or "")}
    if action=="list_storage": return {"ok":True,"devices":lsblk_tree(),**status(req.get("uuid","") or "")}
    raise ValueError("Operación no permitida.")

def main():
    Path(SOCKET).parent.mkdir(parents=True,exist_ok=True)
    try: os.unlink(SOCKET)
    except FileNotFoundError: pass
    sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM); sock.bind(SOCKET)
    gid=grp.getgrnam(APP_GROUP).gr_gid; os.chown(SOCKET,0,gid); os.chmod(SOCKET,0o660); sock.listen(8)
    while True:
        conn,_=sock.accept()
        with conn:
            try:
                raw=b""
                while b"\n" not in raw and len(raw)<65536:
                    part=conn.recv(4096)
                    if not part: break
                    raw+=part
                res=handle(json.loads(raw.split(b"\n",1)[0].decode("utf-8")))
            except Exception as exc: res={"ok":False,"error":str(exc)}
            conn.sendall((json.dumps(res,ensure_ascii=False)+"\n").encode("utf-8"))
if __name__=="__main__": main()
