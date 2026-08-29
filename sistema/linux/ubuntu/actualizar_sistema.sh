#!/usr/bin/env bash
set -Eeuo pipefail

MODE="${1:-}"
APP_ROOT="${PULSIA_APP_ROOT:-/almacen}"
APP_SERVICE="pulsia-inventario"
CADDY_SERVICE="pulsia-inventario-caddy"
STAMP="$(date +%Y%m%d_%H%M%S)"
UPDATE_STARTED=0

info(){ echo "[INFO] $*"; }
ok(){ echo "[OK] $*"; }
warn(){ echo "[AVISO] $*"; }
fail(){ echo "[ERROR] $*" >&2; exit 1; }

[[ "$MODE" == "solo-programa" || "$MODE" == "programa-y-bd" || "$MODE" == "estructural" ]] || fail "Modo de actualización no válido."
[[ ${EUID} -eq 0 ]] || exec sudo -E "$0" "$MODE"

# La actualización SIEMPRE es el proyecto que contiene este script.
SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
[[ -f "$SOURCE_ROOT/manage.py" && -d "$SOURCE_ROOT/inventory" && -d "$SOURCE_ROOT/config" ]] || fail "El script no está dentro de un paquete válido de PULSIA Almacén."

valid_server(){ [[ -d "$1" && -f "$1/manage.py" && -d "$1/inventory" && -d "$1/config" ]]; }
resolve_app_root(){
 if valid_server "$APP_ROOT"; then APP_ROOT="$(cd "$APP_ROOT" && pwd)"; return; fi
 warn "No se ha encontrado el servidor PULSIA Almacén en $APP_ROOT."
 if [[ ! -t 0 ]]; then fail "Servidor no encontrado. Ejecute de forma interactiva o indique PULSIA_APP_ROOT=/ruta/almacen."; fi
 while true; do
  echo
  echo "1) Introducir otra ruta del servidor"
  echo "2) Cerrar sin realizar cambios"
  read -r -p "Seleccione una opción [1/2]: " option
  case "$option" in
   1)
    read -r -p "Ruta de la instalación actual: " candidate
    [[ -n "$candidate" ]] || continue
    if valid_server "$candidate"; then APP_ROOT="$(cd "$candidate" && pwd)"; return; fi
    warn "La ruta indicada no contiene una instalación válida."
    ;;
   2) ok "Actualización cancelada. No se ha realizado ningún cambio."; exit 0 ;;
   *) warn "Opción no válida." ;;
  esac
 done
}
resolve_app_root

info "Actualización incluida en: $SOURCE_ROOT"
info "Servidor instalado en: $APP_ROOT"
info "Modo: $MODE"

if [[ "$(readlink -f "$SOURCE_ROOT")" == "$(readlink -f "$APP_ROOT")" ]]; then
 ok "Este script pertenece a la propia instalación del servidor; no existe una actualización externa que aplicar."
 [[ -t 0 ]] && read -r -p "Pulse Intro para cerrar..." _ || true
 exit 0
fi

command -v rsync >/dev/null || fail "Se necesita rsync."
RSYNC_EXCLUDES=(--exclude='.venv/' --exclude='.env' --exclude='data/' --exclude='backups/' --exclude='logs/' --exclude='certs/' --exclude='__pycache__/' --exclude='*.pyc')
CHANGES="$(rsync -ani --delete "${RSYNC_EXCLUDES[@]}" "$SOURCE_ROOT/" "$APP_ROOT/")"
if [[ -z "$CHANGES" ]]; then
 ok "PULSIA Almacén ya está actualizado. No hay nada que actualizar y no se ha realizado ningún cambio."
 [[ -t 0 ]] && read -r -p "Pulse Intro para cerrar..." _ || true
 exit 0
fi

BACKUP_ROOT="$APP_ROOT/backups/actualizaciones"; BACKUP_DIR="$BACKUP_ROOT/$STAMP"
DB_PATH="$APP_ROOT/data/inventario.sqlite3"; ENV_PATH="$APP_ROOT/.env"
CODE_BACKUP="$BACKUP_DIR/codigo_previo.tar.gz"; DB_BACKUP="$BACKUP_DIR/inventario.sqlite3"; ENV_BACKUP="$BACKUP_DIR/.env"; SYSTEMD_BACKUP="$BACKUP_DIR/systemd"; METADATA_FILE="$BACKUP_DIR/backup_info.txt"
rollback(){ local rc=$?; trap - ERR; echo "[ERROR] La actualización falló. Restaurando automáticamente..." >&2; if [[ $UPDATE_STARTED -eq 1 && -f "$CODE_BACKUP" ]]; then find "$APP_ROOT" -mindepth 1 -maxdepth 1 ! -name '.venv' ! -name '.env' ! -name data ! -name backups ! -name logs ! -name certs -exec rm -rf {} + 2>/dev/null || true; tar -xzf "$CODE_BACKUP" -C "$APP_ROOT" || true; fi; [[ -f "$DB_BACKUP" ]] && cp -a "$DB_BACKUP" "$DB_PATH" || true; [[ -f "$ENV_BACKUP" ]] && cp -a "$ENV_BACKUP" "$ENV_PATH" || true; systemctl daemon-reload >/dev/null 2>&1 || true; systemctl restart "$APP_SERVICE" >/dev/null 2>&1 || true; systemctl restart "$CADDY_SERVICE" >/dev/null 2>&1 || true; exit "$rc"; }
trap rollback ERR

mkdir -p "$BACKUP_DIR"; chmod 0700 "$BACKUP_DIR" || true
systemctl stop "$CADDY_SERVICE" 2>/dev/null || true; systemctl stop "$APP_SERVICE" 2>/dev/null || true
info "Creando backup previo..."
tar -czf "$CODE_BACKUP" -C "$APP_ROOT" --exclude='./.venv' --exclude='./.env' --exclude='./data' --exclude='./backups' --exclude='./logs' --exclude='./certs' --exclude='*/__pycache__' --exclude='*.pyc' .
if [[ -f "$DB_PATH" ]]; then command -v sqlite3 >/dev/null 2>&1 && sqlite3 "$DB_PATH" ".backup '$DB_BACKUP'" || cp -a "$DB_PATH" "$DB_BACKUP"; fi
[[ -f "$ENV_PATH" ]] && cp -a "$ENV_PATH" "$ENV_BACKUP"
mkdir -p "$SYSTEMD_BACKUP"; for unit in /etc/systemd/system/pulsia-inventario.service /etc/systemd/system/pulsia-inventario-caddy.service /etc/systemd/system/pulsia-inventario-storage-admin.service /etc/systemd/system/pulsia-inventario-continuous-backup.service; do [[ -f "$unit" ]] && cp -a "$unit" "$SYSTEMD_BACKUP/"; done
printf 'PULSIA_BACKUP_VERSION=1\nCREATED_AT=%s\nMODE=%s\nAPP_ROOT=%s\nSOURCE_ROOT=%s\nHOSTNAME=%s\n' "$(date --iso-8601=seconds)" "$MODE" "$APP_ROOT" "$SOURCE_ROOT" "$(hostname)" > "$METADATA_FILE"
ln -sfn "$BACKUP_DIR" "$BACKUP_ROOT/ultimo"; UPDATE_STARTED=1

rsync -a --delete "${RSYNC_EXCLUDES[@]}" "$SOURCE_ROOT/" "$APP_ROOT/"
APP_USER="$(systemctl show "$APP_SERVICE" -p User --value 2>/dev/null || true)"; [[ -n "$APP_USER" && "$APP_USER" != root ]] || APP_USER="$(stat -c '%U' "$DB_PATH" 2>/dev/null || stat -c '%U' "$APP_ROOT")"; APP_GROUP="$(id -gn "$APP_USER" 2>/dev/null || stat -c '%G' "$APP_ROOT")"; chown -R "$APP_USER:$APP_GROUP" "$APP_ROOT" || true
find "$APP_ROOT/sistema" -type f -name '*.sh' -exec sed -i 's/\r$//' {} + 2>/dev/null || true; find "$APP_ROOT/sistema" -type f -name '*.sh' -exec chmod 0750 {} + 2>/dev/null || true
[[ -f "$ENV_PATH" ]] && chmod 0600 "$ENV_PATH" || true; [[ -f "$DB_PATH" ]] && chmod 0600 "$DB_PATH" || true
PYTHON="$APP_ROOT/.venv/bin/python"; PIP="$APP_ROOT/.venv/bin/pip"; [[ -x "$PYTHON" ]] || fail "No existe $PYTHON"
REQ=""; [[ -f "$APP_ROOT/requirements/servidor.txt" ]] && REQ="$APP_ROOT/requirements/servidor.txt"; [[ -z "$REQ" && -f "$APP_ROOT/requirements.txt" ]] && REQ="$APP_ROOT/requirements.txt"; [[ -n "$REQ" && -x "$PIP" ]] && "$PIP" install -r "$REQ"
cd "$APP_ROOT"
if [[ "$MODE" != "solo-programa" ]]; then "$PYTHON" manage.py migrate --noinput; else "$PYTHON" manage.py showmigrations --plan | grep -q '\[ \]' && warn "Hay migraciones pendientes que no se aplican en modo solo-programa." || true; fi
"$PYTHON" manage.py check
systemctl daemon-reload; systemctl restart "$APP_SERVICE"; systemctl restart "$CADDY_SERVICE"
systemctl is-active --quiet "$APP_SERVICE" || fail "$APP_SERVICE no está activo"; systemctl is-active --quiet "$CADDY_SERVICE" || fail "$CADDY_SERVICE no está activo"
trap - ERR
ok "Actualización completada correctamente."
echo "Backup de recuperación: $BACKUP_DIR"
