#!/usr/bin/env bash
set -Eeuo pipefail
MODE="${1:-}"; APP_ROOT="${PULSIA_APP_ROOT:-/almacen}"; APP_SERVICE="pulsia-inventario"; CADDY_SERVICE="pulsia-inventario-caddy"; STAMP="$(date +%Y%m%d_%H%M%S)"; UPDATE_STARTED=0
info(){ echo "[INFO] $*"; }; ok(){ echo "[OK] $*"; }; warn(){ echo "[AVISO] $*"; }; fail(){ echo "[ERROR] $*" >&2; exit 1; }
[[ "$MODE" == solo-programa || "$MODE" == programa-y-bd || "$MODE" == estructural ]] || fail "Modo de actualización no válido."; [[ ${EUID} -eq 0 ]] || exec sudo -E "$0" "$MODE"
SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"; [[ -f "$SOURCE_ROOT/manage.py" && -d "$SOURCE_ROOT/inventory" && -d "$SOURCE_ROOT/config" ]] || fail "Paquete PULSIA inválido."
[[ -d "$APP_ROOT" && -f "$APP_ROOT/manage.py" ]] || fail "Servidor no encontrado en $APP_ROOT"; APP_ROOT="$(cd "$APP_ROOT" && pwd)"; [[ "$(readlink -f "$SOURCE_ROOT")" != "$(readlink -f "$APP_ROOT")" ]] || exit 0
command -v rsync >/dev/null || fail "Se necesita rsync."; EX=(--exclude='.venv/' --exclude='.env' --exclude='data/' --exclude='backups/' --exclude='logs/' --exclude='certs/' --exclude='.git/' --exclude='__pycache__/' --exclude='*.pyc')
BACKUP="$APP_ROOT/backups/actualizaciones/$STAMP"; DB_PATH="$APP_ROOT/data/inventario.sqlite3"; ENV_PATH="$APP_ROOT/.env"; mkdir -p "$BACKUP"; chmod 0700 "$BACKUP"; cp -a "$ENV_PATH" "$BACKUP/.env" 2>/dev/null || true; cp -a "$DB_PATH" "$BACKUP/inventario.sqlite3" 2>/dev/null || true; tar -czf "$BACKUP/codigo_previo.tar.gz" -C "$APP_ROOT" --exclude='.venv' --exclude='.env' --exclude='data' --exclude='backups' --exclude='logs' --exclude='certs' --exclude='.git' .
rollback(){ rc=$?; trap - ERR; echo '[ERROR] Fallo. Restaurando backup...' >&2; [[ -f "$BACKUP/.env" ]] && cp -a "$BACKUP/.env" "$ENV_PATH"; [[ -f "$BACKUP/inventario.sqlite3" ]] && cp -a "$BACKUP/inventario.sqlite3" "$DB_PATH"; systemctl restart "$APP_SERVICE" 2>/dev/null || true; exit $rc; }; trap rollback ERR
systemctl stop "$APP_SERVICE" 2>/dev/null || true; info "Sincronizando código y eliminando archivos obsoletos..."; rsync -a --delete "${EX[@]}" "$SOURCE_ROOT/" "$APP_ROOT/"; find "$APP_ROOT/sistema" -type f -name '*.sh' -exec sed -i 's/\r$//' {} + -exec chmod 0750 {} + 2>/dev/null || true
PY="$APP_ROOT/.venv/bin/python"; PIP="$APP_ROOT/.venv/bin/pip"; "$PIP" install -r "$APP_ROOT/requirements/servidor.txt"
unset DATABASE_URL || true; ENV_DB="$(sed -n 's/^[[:space:]]*DATABASE_URL[[:space:]]*=[[:space:]]*//p' "$ENV_PATH" | tail -1 | tr -d '\r' || true)"; info "Motor configurado antes de actualizar: ${ENV_DB%%:*}"
if [[ "$MODE" != solo-programa && "$ENV_DB" != postgresql://* && "$ENV_DB" != postgres://* ]]; then
 [[ -f "$DB_PATH" ]] || fail "No se encuentra la base SQLite original."; info "SQLite detectado: instalando PostgreSQL y migrando la base completa..."
 PULSIA_APP_ROOT="$APP_ROOT" bash "$APP_ROOT/sistema/linux/debian/migrar_sqlite_a_postgresql.sh"; unset DATABASE_URL || true; ok "Conversión SQLite → PostgreSQL terminada."
fi
cd "$APP_ROOT"; if [[ "$MODE" != solo-programa ]]; then "$PY" manage.py migrate --noinput; else "$PY" manage.py showmigrations --plan | grep -q '\[ \]' && warn "Hay migraciones pendientes." || true; fi; "$PY" manage.py check; systemctl daemon-reload; systemctl restart "$APP_SERVICE"; systemctl restart "$CADDY_SERVICE" 2>/dev/null || true; systemctl is-active --quiet "$APP_SERVICE" || fail "Servicio no activo"; trap - ERR; ok "Actualización completada correctamente."; echo "Backup: $BACKUP"
