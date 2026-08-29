#!/usr/bin/env bash
set -Eeuo pipefail

APP_ROOT="/almacen"
APP_SERVICE="pulsia-inventario"
CADDY_SERVICE="pulsia-inventario-caddy"
BACKUP_ROOT="${APP_ROOT}/backups/actualizaciones"
REQUESTED="${1:-ultimo}"

info(){ echo "[INFO] $*"; }
ok(){ echo "[OK] $*"; }
fail(){ echo "[ERROR] $*" >&2; exit 1; }

[[ ${EUID} -eq 0 ]] || exec sudo -E "$0" "$@"
[[ -d "$APP_ROOT" ]] || fail "No existe la instalación $APP_ROOT."

if [[ "$REQUESTED" == "ultimo" ]]; then
  BACKUP_DIR="$(readlink -f "$BACKUP_ROOT/ultimo" 2>/dev/null || true)"
else
  BACKUP_DIR="$(readlink -f "$REQUESTED" 2>/dev/null || true)"
  [[ -n "$BACKUP_DIR" && -d "$BACKUP_DIR" ]] || BACKUP_DIR="$(readlink -f "$BACKUP_ROOT/$REQUESTED" 2>/dev/null || true)"
fi
[[ -n "$BACKUP_DIR" && -d "$BACKUP_DIR" ]] || fail "No se encuentra el backup solicitado. Use: $0 ultimo | $0 AAAAMMDD_HHMMSS | $0 /ruta/backup"
[[ -f "$BACKUP_DIR/codigo_previo.tar.gz" ]] || fail "Backup inválido: falta codigo_previo.tar.gz."

DB_BACKUP="$BACKUP_DIR/inventario.sqlite3"
ENV_BACKUP="$BACKUP_DIR/.env"
SYSTEMD_BACKUP="$BACKUP_DIR/systemd"

cat <<EOF
============================================================
 PULSIA ALMACÉN - VUELTA ATRÁS DE ACTUALIZACIÓN
============================================================
Backup a restaurar: $BACKUP_DIR

Se restaurarán el código anterior y, si existen en el backup,
la base de datos, .env y unidades systemd.
Los directorios backups/, logs/ y certs/ se conservarán.
============================================================
EOF

if [[ "${PULSIA_ROLLBACK_YES:-0}" != "1" ]]; then
  read -r -p "Escriba VOLVER ATRAS para continuar: " CONFIRM
  [[ "$CONFIRM" == "VOLVER ATRAS" ]] || fail "Operación cancelada."
fi

info "Deteniendo servicios..."
systemctl stop "$CADDY_SERVICE" 2>/dev/null || true
systemctl stop "$APP_SERVICE" 2>/dev/null || true
systemctl stop pulsia-inventario-continuous-backup.service 2>/dev/null || true
systemctl stop pulsia-inventario-storage-admin.service 2>/dev/null || true

info "Restaurando código anterior..."
find "$APP_ROOT" -mindepth 1 -maxdepth 1 \
  ! -name '.venv' ! -name '.env' ! -name 'data' ! -name 'backups' \
  ! -name 'logs' ! -name 'certs' -exec rm -rf {} +
tar -xzf "$BACKUP_DIR/codigo_previo.tar.gz" -C "$APP_ROOT"

if [[ -f "$DB_BACKUP" ]]; then
  info "Restaurando base de datos SQLite anterior..."
  mkdir -p "$APP_ROOT/data"
  cp -a "$DB_BACKUP" "$APP_ROOT/data/inventario.sqlite3"
fi
if [[ -f "$ENV_BACKUP" ]]; then
  info "Restaurando .env anterior..."
  cp -a "$ENV_BACKUP" "$APP_ROOT/.env"
  chmod 0600 "$APP_ROOT/.env" || true
fi

if [[ -d "$SYSTEMD_BACKUP" ]]; then
  info "Restaurando unidades systemd anteriores..."
  for unit in "$SYSTEMD_BACKUP"/*.service; do
    [[ -f "$unit" ]] || continue
    cp -a "$unit" "/etc/systemd/system/$(basename "$unit")"
  done
fi

systemctl daemon-reload

info "Comprobando la versión restaurada..."
if [[ -x "$APP_ROOT/.venv/bin/python" && -f "$APP_ROOT/manage.py" ]]; then
  (cd "$APP_ROOT" && "$APP_ROOT/.venv/bin/python" manage.py check) || fail "La versión restaurada no supera manage.py check. Los archivos permanecen restaurados para diagnóstico."
fi

info "Arrancando servicios restaurados..."
systemctl restart "$APP_SERVICE"
systemctl restart "$CADDY_SERVICE"
systemctl restart pulsia-inventario-storage-admin.service 2>/dev/null || true
systemctl restart pulsia-inventario-continuous-backup.service 2>/dev/null || true
systemctl is-active --quiet "$APP_SERVICE" || fail "$APP_SERVICE no ha quedado activo tras la restauración."
systemctl is-active --quiet "$CADDY_SERVICE" || fail "$CADDY_SERVICE no ha quedado activo tras la restauración."

ok "Vuelta atrás completada correctamente."
echo "Restaurado desde: $BACKUP_DIR"
