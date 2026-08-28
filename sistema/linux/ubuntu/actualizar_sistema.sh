#!/usr/bin/env bash
set -Eeuo pipefail

MODE="${1:-}"
shift || true
PACKAGE="${1:-}"

APP_ROOT="/almacen"
APP_SERVICE="pulsia-inventario"
CADDY_SERVICE="pulsia-inventario-caddy"
BACKUP_ROOT="${APP_ROOT}/backups/actualizaciones"
STAMP="$(date +%Y%m%d_%H%M%S)"
WORKDIR=""
SOURCE_ROOT=""
BACKUP_DIR="${BACKUP_ROOT}/${STAMP}"
DB_PATH="${APP_ROOT}/data/inventario.sqlite3"
ENV_PATH="${APP_ROOT}/.env"
CODE_BACKUP="${BACKUP_DIR}/codigo_previo.tar.gz"
DB_BACKUP="${BACKUP_DIR}/inventario.sqlite3"
ENV_BACKUP="${BACKUP_DIR}/.env"
UPDATE_STARTED=0
DB_MAY_HAVE_CHANGED=0

info(){ echo "[INFO] $*"; }
ok(){ echo "[OK] $*"; }
warn(){ echo "[AVISO] $*"; }
fail(){ echo "[ERROR] $*" >&2; exit 1; }

usage(){
  cat <<USAGE
Uso:
  $0 <solo-programa|programa-y-bd|estructural> /ruta/version_nueva.zip
  $0 <solo-programa|programa-y-bd|estructural> /ruta/carpeta_nueva/almacen

También puede ejecutarse desde una versión nueva ya descomprimida sin indicar ruta.
En ese caso el script detectará el proyecto que lo contiene, siempre que NO sea /almacen.
USAGE
}

[[ "$MODE" == "solo-programa" || "$MODE" == "programa-y-bd" || "$MODE" == "estructural" ]] || { usage; fail "Modo de actualización no válido."; }
[[ ${EUID} -eq 0 ]] || exec sudo -E "$0" "$MODE" "$PACKAGE"
[[ -d "$APP_ROOT" && -f "$APP_ROOT/manage.py" ]] || fail "No se encuentra la instalación principal en $APP_ROOT."

cleanup(){
  [[ -n "$WORKDIR" && -d "$WORKDIR" ]] && rm -rf "$WORKDIR" || true
}
trap cleanup EXIT

rollback(){
  local rc=$?
  trap - ERR
  echo
  echo "[ERROR] La actualización falló (código $rc). Iniciando restauración automática..." >&2
  if [[ $UPDATE_STARTED -eq 1 && -f "$CODE_BACKUP" ]]; then
    info "Restaurando código anterior..."
    # Eliminar solo código administrado, preservando datos persistentes.
    find "$APP_ROOT" -mindepth 1 -maxdepth 1 \
      ! -name '.venv' ! -name '.env' ! -name 'data' ! -name 'backups' \
      ! -name 'logs' ! -name 'certs' -exec rm -rf {} + 2>/dev/null || true
    tar -xzf "$CODE_BACKUP" -C "$APP_ROOT" || true
  fi
  if [[ -f "$DB_BACKUP" ]]; then
    info "Restaurando base de datos anterior..."
    cp -a "$DB_BACKUP" "$DB_PATH" || true
  fi
  if [[ -f "$ENV_BACKUP" ]]; then
    cp -a "$ENV_BACKUP" "$ENV_PATH" || true
  fi
  systemctl daemon-reload >/dev/null 2>&1 || true
  systemctl restart "$APP_SERVICE" >/dev/null 2>&1 || true
  systemctl restart "$CADDY_SERVICE" >/dev/null 2>&1 || true
  echo "[ERROR] Se ha intentado restaurar automáticamente la instalación previa." >&2
  exit "$rc"
}
trap rollback ERR

resolve_source(){
  local script_project
  script_project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." 2>/dev/null && pwd || true)"

  if [[ -z "$PACKAGE" ]]; then
    if [[ -n "$script_project" && "$script_project" != "$APP_ROOT" && -f "$script_project/manage.py" ]]; then
      SOURCE_ROOT="$script_project"
      return
    fi
    usage
    fail "Indique el ZIP o la carpeta de la nueva versión."
  fi

  if [[ -d "$PACKAGE" ]]; then
    if [[ -f "$PACKAGE/manage.py" ]]; then
      SOURCE_ROOT="$(cd "$PACKAGE" && pwd)"
    elif [[ -f "$PACKAGE/almacen/manage.py" ]]; then
      SOURCE_ROOT="$(cd "$PACKAGE/almacen" && pwd)"
    else
      fail "La carpeta indicada no contiene un proyecto Almacén válido (manage.py)."
    fi
  elif [[ -f "$PACKAGE" ]]; then
    command -v unzip >/dev/null 2>&1 || fail "Se necesita 'unzip' para actualizar desde un ZIP."
    WORKDIR="$(mktemp -d /tmp/pulsia-update.XXXXXX)"
    unzip -q "$PACKAGE" -d "$WORKDIR"
    local found
    found="$(find "$WORKDIR" -maxdepth 4 -type f -name manage.py -print -quit)"
    [[ -n "$found" ]] || fail "El ZIP no contiene manage.py."
    SOURCE_ROOT="$(dirname "$found")"
  else
    fail "No existe el paquete de actualización: $PACKAGE"
  fi

  [[ "$(readlink -f "$SOURCE_ROOT")" != "$(readlink -f "$APP_ROOT")" ]] || fail "La fuente de actualización no puede ser la propia instalación /almacen."
  [[ -d "$SOURCE_ROOT/inventory" && -d "$SOURCE_ROOT/config" ]] || fail "Paquete incompleto: faltan inventory/ o config/."
}

resolve_source
info "Fuente nueva: $SOURCE_ROOT"
info "Destino      : $APP_ROOT"
info "Modo         : $MODE"

mkdir -p "$BACKUP_DIR"
chmod 0700 "$BACKUP_DIR" || true

info "Deteniendo temporalmente la aplicación web..."
systemctl stop "$CADDY_SERVICE" 2>/dev/null || true
systemctl stop "$APP_SERVICE" 2>/dev/null || true

info "Creando copia de seguridad previa..."
# Backup de código, excluyendo datos persistentes y entorno virtual.
tar -czf "$CODE_BACKUP" -C "$APP_ROOT" \
  --exclude='./.venv' --exclude='./.env' --exclude='./data' --exclude='./backups' \
  --exclude='./logs' --exclude='./certs' --exclude='*/__pycache__' --exclude='*.pyc' .

if [[ -f "$DB_PATH" ]]; then
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$DB_PATH" ".backup '$DB_BACKUP'"
  else
    cp -a "$DB_PATH" "$DB_BACKUP"
  fi
fi
[[ -f "$ENV_PATH" ]] && cp -a "$ENV_PATH" "$ENV_BACKUP"
ok "Backup previo: $BACKUP_DIR"

UPDATE_STARTED=1

info "Copiando nueva versión del programa..."
command -v rsync >/dev/null 2>&1 || fail "Se necesita rsync para realizar la actualización segura."
rsync -a --delete \
  --exclude='.venv/' --exclude='.env' --exclude='data/' --exclude='backups/' \
  --exclude='logs/' --exclude='certs/' --exclude='__pycache__/' --exclude='*.pyc' \
  "$SOURCE_ROOT/" "$APP_ROOT/"

APP_USER="$(systemctl show "$APP_SERVICE" -p User --value 2>/dev/null || true)"
[[ -n "$APP_USER" && "$APP_USER" != "root" ]] || APP_USER="$(stat -c '%U' "$DB_PATH" 2>/dev/null || stat -c '%U' "$APP_ROOT")"
APP_GROUP="$(id -gn "$APP_USER" 2>/dev/null || stat -c '%G' "$APP_ROOT")"
chown -R "$APP_USER:$APP_GROUP" "$APP_ROOT" || true
[[ -f "$ENV_PATH" ]] && chmod 0600 "$ENV_PATH" || true
[[ -f "$DB_PATH" ]] && chmod 0600 "$DB_PATH" || true
find "$APP_ROOT/sistema" -type f -name '*.sh' -exec chmod 0750 {} + 2>/dev/null || true
chmod 0750 "$APP_ROOT/manage.py" "$APP_ROOT/gestionar_pulsia.sh" 2>/dev/null || true

PYTHON="$APP_ROOT/.venv/bin/python"
PIP="$APP_ROOT/.venv/bin/pip"
[[ -x "$PYTHON" ]] || fail "No existe el entorno virtual esperado: $PYTHON"

REQ=""
[[ -f "$APP_ROOT/requirements/servidor.txt" ]] && REQ="$APP_ROOT/requirements/servidor.txt"
[[ -z "$REQ" && -f "$APP_ROOT/requirements.txt" ]] && REQ="$APP_ROOT/requirements.txt"
if [[ -n "$REQ" && -x "$PIP" ]]; then
  info "Actualizando dependencias Python necesarias..."
  "$PIP" install -r "$REQ"
fi

cd "$APP_ROOT"
if [[ "$MODE" == "programa-y-bd" || "$MODE" == "estructural" ]]; then
  DB_MAY_HAVE_CHANGED=1

  if [[ "$MODE" == "estructural" ]]; then
    info "Generando huella de seguridad del inventario antes de migrar..."
    "$PYTHON" - <<'PYSAFE' > "$BACKUP_DIR/inventario_antes.sha256"
import os, hashlib, json
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django; django.setup()
from inventory.models import InventoryTable, InventoryRecord
def norm(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",",":"), default=str)
h=hashlib.sha256()
tables=list(InventoryTable.objects.order_by("pk").values())
records=list(InventoryRecord.objects.order_by("pk").values())
for obj in (tables, records): h.update(norm(obj).encode("utf-8"))
print(f"tables={len(tables)} records={len(records)} sha256={h.hexdigest()}")
PYSAFE
    cat "$BACKUP_DIR/inventario_antes.sha256"
    info "Modo ESTRUCTURAL: la BD instalada se conserva; solo se aplican migraciones sobre ella."
  fi

  info "Aplicando migraciones estructurales de base de datos..."
  "$PYTHON" manage.py migrate --noinput
  ok "Migraciones aplicadas."

  if [[ "$MODE" == "estructural" ]]; then
    info "Verificando que los datos de componentes/inventario no hayan sido modificados..."
    "$PYTHON" - <<'PYSAFE' > "$BACKUP_DIR/inventario_despues.sha256"
import os, hashlib, json
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django; django.setup()
from inventory.models import InventoryTable, InventoryRecord
def norm(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",",":"), default=str)
h=hashlib.sha256()
tables=list(InventoryTable.objects.order_by("pk").values())
records=list(InventoryRecord.objects.order_by("pk").values())
for obj in (tables, records): h.update(norm(obj).encode("utf-8"))
print(f"tables={len(tables)} records={len(records)} sha256={h.hexdigest()}")
PYSAFE
    cat "$BACKUP_DIR/inventario_despues.sha256"
    if ! cmp -s "$BACKUP_DIR/inventario_antes.sha256" "$BACKUP_DIR/inventario_despues.sha256"; then
      fail "PROTECCIÓN ACTIVADA: una migración ha modificado datos de componentes/inventario. Se restaurará automáticamente la BD anterior."
    fi
    ok "Inventario protegido: contenido idéntico antes y después de la actualización."
  fi
else
  info "Modo SOLO PROGRAMA: no se ejecutarán migraciones."
  set +e
  PENDING="$($PYTHON manage.py showmigrations --plan 2>/dev/null | grep '^\[ \]' | head -20)"
  set -e
  if [[ -n "$PENDING" ]]; then
    warn "La nueva versión contiene migraciones pendientes. No se han aplicado por diseño:"
    echo "$PENDING"
    warn "Si esta versión requiere esos cambios, utilice 08_actualizar_programa_y_bd.sh."
  fi
fi

info "Verificando configuración Django..."
"$PYTHON" manage.py check

systemctl daemon-reload
info "Arrancando servicios..."
systemctl restart "$APP_SERVICE"
systemctl restart "$CADDY_SERVICE"
systemctl is-active --quiet "$APP_SERVICE" || fail "$APP_SERVICE no ha quedado activo."
systemctl is-active --quiet "$CADDY_SERVICE" || fail "$CADDY_SERVICE no ha quedado activo."

trap - ERR
ok "Actualización completada correctamente."
echo "Backup de seguridad: $BACKUP_DIR"
if [[ "$MODE" == "solo-programa" ]]; then
  echo "Base de datos: CONSERVADA SIN MIGRACIONES"
elif [[ "$MODE" == "estructural" ]]; then
  echo "Base de datos: CONSERVADA; esquema actualizado; inventario/componentes verificados por huella SHA-256"
else
  echo "Base de datos: CONSERVADA Y ACTUALIZADA MEDIANTE MIGRACIONES"
fi
