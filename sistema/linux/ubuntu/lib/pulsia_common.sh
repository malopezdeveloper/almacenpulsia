#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
find_project_root(){
  local d="$SCRIPT_DIR" i
  for i in 1 2 3 4 5; do
    if [[ -f "$d/manage.py" ]]; then printf '%s\n' "$d"; return 0; fi
    d="$(dirname "$d")"
  done
  return 1
}
PROJECT_ROOT="$(find_project_root)" || { echo "[ERROR] No se encontró manage.py ascendiendo desde $SCRIPT_DIR" >&2; exit 1; }
SERVICE_NAME="pulsia-inventario"
CADDY_SERVICE_NAME="pulsia-inventario-caddy"
SYSTEM_CONFIG_DIR="/etc/pulsia-inventario"
CLIENT_APP_DIR="$PROJECT_ROOT/cliente/PULSIA_Inventario_Cliente"
APP_CLIENT_OUTPUT_DIR="$PROJECT_ROOT/app cliente"
LOG_DIR="$PROJECT_ROOT/logs"
BACKEND_HOST="127.0.0.1"
BACKEND_PORT="8080"
CADDY_SITE="almacen"

ok(){ printf '\033[32m[OK]\033[0m %s\n' "$*"; }
info(){ printf '\033[36m[INFO]\033[0m %s\n' "$*"; }
warn(){ printf '\033[33m[AVISO]\033[0m %s\n' "$*"; }
fail(){ printf '\033[31m[ERROR]\033[0m %s\n' "$*" >&2; exit 1; }
require_root(){ [[ ${EUID:-$(id -u)} -eq 0 ]] || fail "Ejecute con sudo: sudo $0"; }
require_service_install(){
  [[ -f "/etc/systemd/system/${SERVICE_NAME}.service" || -f "/lib/systemd/system/${SERVICE_NAME}.service" ]] || \
    fail "El servicio PULSIA no está instalado. Ejecute primero 01_instalar_servicio.sh."
}
service_active(){ systemctl is-active --quiet "$1"; }
show_failed_logs(){
  local svc="$1"
  journalctl -u "$svc" -n 50 --no-pager 2>/dev/null || true
}
find_caddy_root_cert(){
  local data="/var/lib/${CADDY_SERVICE_NAME}" cert
  cert="$(find "$data" -type f -path '*/caddy/pki/authorities/local/root.crt' -print -quit 2>/dev/null || true)"
  [[ -n "$cert" ]] || cert="$(find "$data" -type f -path '*/pki/authorities/local/root.crt' -print -quit 2>/dev/null || true)"
  printf '%s\n' "$cert"
}
run_user(){
  local u="${SUDO_USER:-$(logname 2>/dev/null || true)}"
  [[ -n "$u" && "$u" != root ]] || u="${PULSIA_RUN_USER:-root}"
  printf '%s\n' "$u"
}
