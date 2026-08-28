#!/usr/bin/env bash
set -Eeuo pipefail

SERVICE_NAME="pulsia-inventario"
CADDY_SERVICE_NAME="pulsia-inventario-caddy"
APP_URL=""
CADDY_DATA_DIR="/var/lib/pulsia-inventario-caddy"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
find_project_root(){
  local d="$SCRIPT_DIR" i
  for i in 1 2 3 4 5; do
    if [[ -f "$d/manage.py" ]]; then printf '%s\n' "$d"; return 0; fi
    d="$(dirname "$d")"
  done
  return 1
}
PROJECT_ROOT="$(find_project_root)" || { echo "[ERROR] No se encontró manage.py ascendiendo desde $SCRIPT_DIR" >&2; exit 1; }
LOG_DIR="$PROJECT_ROOT/logs"
RESTART_LOG="$LOG_DIR/reinicio_linux.log"

ok(){ printf '\033[32m[OK]\033[0m %s\n' "$*"; }
info(){ printf '\033[36m[INFO]\033[0m %s\n' "$*"; }
warn(){ printf '\033[33m[AVISO]\033[0m %s\n' "$*"; }
fail(){ printf '\033[31m[ERROR]\033[0m %s\n' "$*" >&2; exit 1; }

if [[ $EUID -ne 0 ]]; then
  exec sudo -E bash "$0" "$@"
fi
[[ -f "$PROJECT_ROOT/manage.py" ]] || fail "No se encuentra manage.py en $PROJECT_ROOT."
mkdir -p "$LOG_DIR"; touch "$RESTART_LOG"; chmod 640 "$RESTART_LOG" || true; exec > >(tee -a "$RESTART_LOG") 2>&1
info "Log: $RESTART_LOG"
command -v systemctl >/dev/null 2>&1 || fail "systemd/systemctl no está disponible. Use el instalador en un Debian/Ubuntu compatible."

info "PULSIA Inventario Técnico - reinicio de servicios"
info "Proyecto detectado: $PROJECT_ROOT"
VIRT_TYPE="$(systemd-detect-virt --vm 2>/dev/null || true)"
[[ -n "$VIRT_TYPE" ]] || VIRT_TYPE="none"
if [[ "$VIRT_TYPE" != none ]]; then info "Máquina virtual: $VIRT_TYPE"; fi
VM_IP="$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')"
VM_GW="$(ip route show default 2>/dev/null | awk '{print $3; exit}')"
if [[ "$VIRT_TYPE" =~ ^(oracle|vbox|virtualbox)$ ]] && [[ "$VM_IP" == 10.0.2.* && "$VM_GW" == 10.0.2.2 ]]; then
  warn "VirtualBox parece seguir en NAT ($VM_IP). Los clientes LAN pueden no alcanzar la IP del servidor. Use Adaptador puente."
fi

systemctl list-unit-files "$SERVICE_NAME.service" >/dev/null 2>&1 || fail "El servicio $SERVICE_NAME no está instalado. Ejecute primero sistema/linux/debian/instalar_todo.sh."
systemctl list-unit-files "$CADDY_SERVICE_NAME.service" >/dev/null 2>&1 || fail "El servicio $CADDY_SERVICE_NAME no está instalado. Ejecute primero el instalador."

info "Deteniendo servicios PULSIA..."
systemctl stop "$CADDY_SERVICE_NAME" || true
systemctl stop "$SERVICE_NAME" || true
sleep 1

# No se mata ningún python/caddy global. Solo se comprueba que nuestras unidades se hayan detenido.
if systemctl is-active --quiet "$SERVICE_NAME"; then
  journalctl -u "$SERVICE_NAME" -n 40 --no-pager || true
  fail "El servicio Django/Waitress de PULSIA no se ha detenido correctamente."
fi
if systemctl is-active --quiet "$CADDY_SERVICE_NAME"; then
  journalctl -u "$CADDY_SERVICE_NAME" -n 40 --no-pager || true
  fail "El servicio Caddy de PULSIA no se ha detenido correctamente."
fi
ok "Servicios detenidos."

info "Saneando procesos residuales antes del reinicio..."
# Caddy: en el servidor dedicado se eliminan procesos residuales que hayan quedado fuera de systemd.
while IFS= read -r pid; do
  [[ -n "$pid" ]] || continue
  cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
  warn "Finalizando Caddy residual PID $pid ${cmd:+| $cmd}"
  kill "$pid" >/dev/null 2>&1 || true
  sleep 0.2
  kill -9 "$pid" >/dev/null 2>&1 || true
done < <(pgrep -x caddy 2>/dev/null || true)
# Python: solo Waitress/PULSIA en 8080.
while IFS= read -r pid; do
  [[ -n "$pid" ]] || continue
  cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
  exe="$(readlink -f "/proc/$pid/exe" 2>/dev/null || true)"
  if [[ "$cmd" == *waitress* && ( "$cmd" == *"config.wsgi"* || "$cmd" == *":8080"* ) ]] || [[ "$cmd" == *"$PROJECT_ROOT"* && "$exe" == *python* ]]; then
    warn "Finalizando backend PULSIA residual PID $pid | $cmd"
    kill "$pid" >/dev/null 2>&1 || true
    sleep 0.2
    kill -9 "$pid" >/dev/null 2>&1 || true
  fi
done < <(ss -ltnp 2>/dev/null | awk '$4 ~ /:8080$/ {if(match($0,/pid=[0-9]+/)){x=substr($0,RSTART+4,RLENGTH-4); print x}}' | sort -u)

info "Arrancando servicios PULSIA..."
systemctl start "$SERVICE_NAME"
sleep 1
systemctl start "$CADDY_SERVICE_NAME"
sleep 2

if ! systemctl is-active --quiet "$SERVICE_NAME"; then
  journalctl -u "$SERVICE_NAME" -n 60 --no-pager || true
  fail "Django/Waitress no ha arrancado."
fi
if ! systemctl is-active --quiet "$CADDY_SERVICE_NAME"; then
  journalctl -u "$CADDY_SERVICE_NAME" -n 60 --no-pager || true
  fail "Caddy no ha arrancado."
fi
ok "Servicios activos."

if curl -fsS -H "Host: almacen" -H "X-Forwarded-Proto: https" http://127.0.0.1:8080/ -o /dev/null; then ok "Backend responde en 127.0.0.1:8080."; else warn "Backend activo pero la comprobación interna no respondió."; fi
LAN_IP="$(ip -o -4 addr show scope global 2>/dev/null | awk '{split($4,a,"/"); print a[1]; exit}')"
if [[ -n "$LAN_IP" ]]; then
  APP_URL="https://$LAN_IP"
  CA_FILE="$PROJECT_ROOT/certs/PULSIA-Inventario-Root-CA.crt"
  if [[ -f "$CA_FILE" ]] && curl --cacert "$CA_FILE" -fsS "$APP_URL/" -o /dev/null; then ok "Acceso HTTPS por IP responde y valida en $APP_URL"; else warn "HTTPS por IP todavía no responde o no valida. Revise TCP/443, Caddy y la CA PULSIA."; fi
else
  warn "No se pudo determinar la IP LAN para el health-check."
fi

# Abrir la aplicación en el escritorio desde el que se lanzó sudo, sin tocar usuarios ni contraseñas.
TARGET_USER="${SUDO_USER:-}"
if [[ -n "$TARGET_USER" && "$TARGET_USER" != root ]] && command -v xdg-open >/dev/null 2>&1 && [[ -n "${DISPLAY:-}" ]]; then
  sudo -u "$TARGET_USER" env DISPLAY="$DISPLAY" xdg-open "$APP_URL" >/dev/null 2>&1 || warn "No se pudo abrir el navegador automáticamente."
else
  info "Servidor sin escritorio o sesión gráfica: abra $APP_URL desde el navegador de otro PC de la LAN."
fi
