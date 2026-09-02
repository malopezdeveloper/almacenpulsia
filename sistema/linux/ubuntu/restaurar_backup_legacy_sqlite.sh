#!/usr/bin/env bash
set -Eeuo pipefail
APP_ROOT="${PULSIA_APP_ROOT:-/almacen}"
SERVICE="pulsia-inventario"
SOURCE="${1:-}"
[[ $EUID -eq 0 ]] || exec sudo -E bash "$0" "$@"
[[ -n "$SOURCE" && -f "$SOURCE" ]] || { echo "Uso: $0 /ruta/backup.sqlite3" >&2; exit 2; }
file "$SOURCE" | grep -qi 'SQLite' || { echo "El archivo no es una base SQLite válida." >&2; exit 3; }
[[ -f "$APP_ROOT/.env" ]] || { echo "Falta $APP_ROOT/.env" >&2; exit 4; }
grep -Eq '^DATABASE_URL=postgres(ql)?://' "$APP_ROOT/.env" || { echo "El servidor destino debe estar ya configurado con PostgreSQL." >&2; exit 5; }
APP_USER="$(systemctl show "$SERVICE" -p User --value 2>/dev/null || true)"; [[ -n "$APP_USER" && "$APP_USER" != root ]] || APP_USER="$(stat -c '%U' "$APP_ROOT")"
APP_GROUP="$(id -gn "$APP_USER")"
STAMP="$(date +%Y%m%d_%H%M%S)"; WORK="$APP_ROOT/backups/restauracion_legacy_sqlite/$STAMP"; mkdir -p "$WORK"; cp -a "$SOURCE" "$WORK/legacy.sqlite3"; chown -R "$APP_USER:$APP_GROUP" "$WORK"
PY="$APP_ROOT/.venv/bin/python"; DBURL="$(sed -n 's/^DATABASE_URL=//p' "$APP_ROOT/.env" | tail -n1)"
# Conserva el PostgreSQL actual antes de sustituir datos.
PGPASSWORD="$($PY -c 'from urllib.parse import urlparse,unquote; import sys; print(unquote(urlparse(sys.argv[1]).password or ""))' "$DBURL")" \
pg_dump "$DBURL" --format=custom --no-owner --no-privileges --file "$WORK/postgresql_antes.pgdump"
# Exporta el SQLite histórico usando temporalmente el modo de compatibilidad.
cp -a "$APP_ROOT/data/inventario.sqlite3" "$WORK/sqlite_actual" 2>/dev/null || true
mkdir -p "$APP_ROOT/data"; cp -a "$SOURCE" "$APP_ROOT/data/inventario.sqlite3"; chown "$APP_USER:$APP_GROUP" "$APP_ROOT/data/inventario.sqlite3"
sudo -u "$APP_USER" env PULSIA_SQLITE_MIGRATION=1 DATABASE_URL= "$PY" "$APP_ROOT/manage.py" dumpdata --natural-foreign --natural-primary --exclude contenttypes --exclude auth.permission --output "$WORK/legacy.json"
rm -f "$APP_ROOT/data/inventario.sqlite3"; [[ ! -f "$WORK/sqlite_actual" ]] || mv "$WORK/sqlite_actual" "$APP_ROOT/data/inventario.sqlite3"
# La restauración destructiva solo comienza después de tener ambos backups.
systemctl stop "$SERVICE" 2>/dev/null || true
sudo -u "$APP_USER" env DATABASE_URL="$DBURL" "$PY" "$APP_ROOT/manage.py" flush --noinput
sudo -u "$APP_USER" env DATABASE_URL="$DBURL" "$PY" "$APP_ROOT/manage.py" migrate --noinput
sudo -u "$APP_USER" env DATABASE_URL="$DBURL" "$PY" "$APP_ROOT/manage.py" loaddata "$WORK/legacy.json"
sudo -u "$APP_USER" env DATABASE_URL="$DBURL" "$PY" "$APP_ROOT/manage.py" check
systemctl restart "$SERVICE"; systemctl is-active --quiet "$SERVICE"
chown -R root:root "$WORK"; chmod 0700 "$WORK"
echo "Backup SQLite histórico convertido y restaurado en PostgreSQL. Backup previo: $WORK/postgresql_antes.pgdump"
