#!/usr/bin/env bash
set -Eeuo pipefail
APP_ROOT="${PULSIA_APP_ROOT:-/almacen}"; SERVICE="pulsia-inventario"; SQLITE="$APP_ROOT/data/inventario.sqlite3"; ENV="$APP_ROOT/.env"; STAMP="$(date +%Y%m%d_%H%M%S)"; BACKUP="$APP_ROOT/backups/migracion_postgresql/$STAMP"; DB_NAME="${PULSIA_PG_DB:-pulsia_almacen}"; DB_USER="${PULSIA_PG_USER:-pulsia}"
[[ $EUID -eq 0 ]] || exec sudo -E "$0" "$@"
[[ -f "$SQLITE" ]] || { echo "No existe $SQLITE" >&2; exit 1; }; [[ -f "$ENV" ]] || { echo "No existe $ENV" >&2; exit 1; }
apt-get update; DEBIAN_FRONTEND=noninteractive apt-get install -y postgresql postgresql-client openssl; systemctl enable --now postgresql
APP_USER="$(systemctl show "$SERVICE" -p User --value 2>/dev/null || true)"; [[ -n "$APP_USER" && "$APP_USER" != root ]] || APP_USER="$(stat -c '%U' "$APP_ROOT")"
mkdir -p "$BACKUP"; chmod 0700 "$BACKUP"; cp -a "$SQLITE" "$BACKUP/inventario.sqlite3"; cp -a "$ENV" "$BACKUP/.env"; chown "$APP_USER" "$BACKUP"; chmod 0700 "$BACKUP"
PY="$APP_ROOT/.venv/bin/python"; [[ -x "$PY" ]] || exit 1; "$APP_ROOT/.venv/bin/pip" install 'psycopg[binary]>=3.3.4,<4'
PG_PASS="${PULSIA_PG_PASSWORD:-$(openssl rand -hex 24)}"
sudo -u postgres psql -v ON_ERROR_STOP=1 --set=dbuser="$DB_USER" --set=dbpass="$PG_PASS" --set=dbname="$DB_NAME" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'dbuser', :'dbpass') WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname=:'dbuser') \gexec
SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L', :'dbuser', :'dbpass') \gexec
SELECT format('CREATE DATABASE %I OWNER %I', :'dbname', :'dbuser') WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname=:'dbname') \gexec
SQL
systemctl stop "$SERVICE" 2>/dev/null || true; cd "$APP_ROOT"
sudo -u "$APP_USER" env PULSIA_SQLITE_MIGRATION=1 DATABASE_URL= "$PY" manage.py dumpdata --natural-foreign --natural-primary --exclude contenttypes --exclude auth.permission --output "$BACKUP/sqlite_export.json"
chown root:root "$BACKUP" "$BACKUP/sqlite_export.json" 2>/dev/null || true; chmod 0700 "$BACKUP"; chmod 0600 "$BACKUP/sqlite_export.json" 2>/dev/null || true
ENC_PASS="$($PY -c 'from urllib.parse import quote; import sys; print(quote(sys.argv[1], safe=""))' "$PG_PASS")"; DATABASE_URL="postgresql://${DB_USER}:${ENC_PASS}@127.0.0.1:5432/${DB_NAME}"
if grep -q '^DATABASE_URL=' "$ENV"; then sed -i "s|^DATABASE_URL=.*|DATABASE_URL=$DATABASE_URL|" "$ENV"; else printf '\nDATABASE_URL=%s\n' "$DATABASE_URL" >> "$ENV"; fi; chmod 0600 "$ENV"
set +e
sudo -u "$APP_USER" env DATABASE_URL="$DATABASE_URL" "$PY" manage.py migrate --noinput; M1=$?
[[ $M1 -eq 0 ]] && sudo -u "$APP_USER" env DATABASE_URL="$DATABASE_URL" "$PY" manage.py loaddata "$BACKUP/sqlite_export.json"; M2=$?
[[ $M1 -eq 0 && $M2 -eq 0 ]] && sudo -u "$APP_USER" env DATABASE_URL="$DATABASE_URL" "$PY" manage.py check; M3=$?
set -e
if [[ $M1 -ne 0 || $M2 -ne 0 || $M3 -ne 0 ]]; then cp -a "$BACKUP/.env" "$ENV"; systemctl restart "$SERVICE" 2>/dev/null || true; echo "Migración fallida; restaurada configuración SQLite. Backup: $BACKUP" >&2; exit 1; fi
mv "$SQLITE" "$BACKUP/inventario.sqlite3.original"; systemctl restart "$SERVICE"; systemctl is-active --quiet "$SERVICE"; echo "Migración PostgreSQL completada. Backup: $BACKUP"
