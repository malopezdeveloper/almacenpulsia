#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
CERT_FILE="$SCRIPT_DIR/PULSIA-Inventario-Root-CA.crt"
CONFIG_FILE="$SCRIPT_DIR/servidor_cliente.ini"
APP_HOST="almacen"
APP_URL="https://almacen"
SERVER_IP="${1:-}"
EXPECTED_SHA256=""
ORIGINAL_USER="${SUDO_USER:-${USER:-}}"
LOG_DIR="/var/log"
CLIENT_LOG="$LOG_DIR/pulsia-inventario-cliente-linux.log"
CURRENT_PHASE="inicio"

ok(){ printf '\033[32m[OK]\033[0m %s\n' "$*"; }
info(){ printf '\033[36m[INFO]\033[0m %s\n' "$*"; }
warn(){ printf '\033[33m[AVISO]\033[0m %s\n' "$*"; }
fail(){ printf '\033[31m[ERROR]\033[0m %s\n' "$*" >&2; exit 1; }
phase(){ CURRENT_PHASE="$1"; info "[FASE] $1"; }
on_error(){ rc=$?; printf '\n[ERROR] Fase %s, linea %s, codigo %s: %s\n' "$CURRENT_PHASE" "${BASH_LINENO[0]:-?}" "$rc" "${BASH_COMMAND:-?}" >&2; exit "$rc"; }
trap on_error ERR

if [[ $EUID -ne 0 ]]; then exec sudo -E bash "$0" "$@"; fi
touch "$CLIENT_LOG" 2>/dev/null || CLIENT_LOG="/tmp/pulsia-inventario-cliente-linux.log"
exec > >(tee -a "$CLIENT_LOG") 2>&1
phase "01 Validacion del paquete"

phase "02 Configuracion del servidor"
if [[ -f "$CONFIG_FILE" ]]; then
  while IFS='=' read -r k v; do
    case "$k" in
      SERVER_IP) [[ -z "$SERVER_IP" ]] && SERVER_IP="$v" ;;
      CA_SHA256) EXPECTED_SHA256="$v" ;;
    esac
  done < "$CONFIG_FILE"
fi

[[ -f "$CERT_FILE" ]] || fail "Falta $CERT_FILE. Use la carpeta/paquete de cliente generado por el servidor después de instalarlo; no se descarga automáticamente una CA raíz desde una conexión no confiable."

if [[ -n "$EXPECTED_SHA256" ]]; then
  ACTUAL_SHA256="$(sha256sum "$CERT_FILE" | awk '{print toupper($1)}')"
  [[ "${ACTUAL_SHA256^^}" == "${EXPECTED_SHA256^^}" ]] || fail "La huella SHA256 de la CA no coincide con la generada por el servidor."
  ok "Huella de la CA verificada."
fi

if [[ -z "$SERVER_IP" ]]; then
  SERVER_IP="$(getent ahostsv4 "$APP_HOST" 2>/dev/null | awk 'NR==1{print $1}' || true)"
fi
if [[ -z "$SERVER_IP" ]]; then
  read -r -p "Introduzca la IP LAN del servidor PULSIA: " SERVER_IP
fi
python3 - "$SERVER_IP" <<'PY' || fail "IP no válida: $SERVER_IP"
import ipaddress,sys
ip=ipaddress.ip_address(sys.argv[1])
assert ip.version == 4
PY

CURRENT_IP="$(getent ahostsv4 "$APP_HOST" 2>/dev/null | awk 'NR==1{print $1}' || true)"
if [[ "$CURRENT_IP" != "$SERVER_IP" ]]; then
  sed -i -E '/^[[:space:]]*[^#[:space:]]+[[:space:]]+almacen([[:space:]]|$)/d' /etc/hosts
  printf '%s almacen # PULSIA Inventario\n' "$SERVER_IP" >> /etc/hosts
  ok "Resolución local configurada: almacen -> $SERVER_IP"
else
  ok "almacen ya resuelve a $SERVER_IP; se conserva la resolución existente."
fi

phase "03 Certificados de confianza"
command -v update-ca-certificates >/dev/null 2>&1 || fail "No existe update-ca-certificates. Instale ca-certificates."
install -m 0644 "$CERT_FILE" /usr/local/share/ca-certificates/PULSIA-Inventario-Root-CA.crt
update-ca-certificates >/dev/null
ok "CA PULSIA instalada en el almacén del sistema."

if ! command -v certutil >/dev/null 2>&1 && command -v apt-get >/dev/null 2>&1; then
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends libnss3-tools >/dev/null 2>&1 || warn "No se pudo instalar libnss3-tools; el almacén del sistema sí quedó actualizado."
fi

install_nss_for_user(){
  local usr="$1" home group nssdb profile
  [[ -n "$usr" && "$usr" != root ]] || return 0
  home="$(getent passwd "$usr" | cut -d: -f6)"; [[ -d "$home" ]] || return 0
  group="$(id -gn "$usr")"
  command -v certutil >/dev/null 2>&1 || return 0
  nssdb="$home/.pki/nssdb"
  install -d -m 700 -o "$usr" -g "$group" "$nssdb"
  [[ -f "$nssdb/cert9.db" ]] || sudo -u "$usr" certutil -N -d "sql:$nssdb" --empty-password >/dev/null 2>&1 || true
  sudo -u "$usr" certutil -D -d "sql:$nssdb" -n "PULSIA Inventario Root CA" >/dev/null 2>&1 || true
  sudo -u "$usr" certutil -A -d "sql:$nssdb" -n "PULSIA Inventario Root CA" -t "C,," -i "$CERT_FILE"
  if [[ -d "$home/.mozilla/firefox" ]]; then
    while IFS= read -r profile; do
      sudo -u "$usr" certutil -D -d "sql:$profile" -n "PULSIA Inventario Root CA" >/dev/null 2>&1 || true
      sudo -u "$usr" certutil -A -d "sql:$profile" -n "PULSIA Inventario Root CA" -t "C,," -i "$CERT_FILE" >/dev/null 2>&1 || true
    done < <(find "$home/.mozilla/firefox" -mindepth 1 -maxdepth 1 -type d -exec test -f '{}/cert9.db' ';' -print 2>/dev/null)
  fi
}
install_nss_for_user "$ORIGINAL_USER"

FINAL_IP="$(getent ahostsv4 "$APP_HOST" 2>/dev/null | awk 'NR==1{print $1}' || true)"
[[ -n "$FINAL_IP" ]] || fail "No se puede resolver 'almacen'."
ok "almacen resuelve a $FINAL_IP"

if command -v timeout >/dev/null 2>&1; then
  timeout 5 bash -c "</dev/tcp/$APP_HOST/443" 2>/dev/null || fail "TCP/443 no es accesible. Revise firewall/ESET/ruta LAN."
fi
ok "TCP/443 accesible."

curl -fsS "$APP_URL/" -o /dev/null || fail "HTTPS no valida correctamente con la CA instalada. Cierre completamente el navegador y compruebe que el servidor utiliza la misma CA."
ok "$APP_URL responde con certificado de confianza."

TARGET_USER="${SUDO_USER:-}"
if [[ -n "$TARGET_USER" && "$TARGET_USER" != root ]] && command -v xdg-open >/dev/null 2>&1 && [[ -n "${DISPLAY:-}" ]]; then
  sudo -u "$TARGET_USER" env DISPLAY="$DISPLAY" xdg-open "$APP_URL" >/dev/null 2>&1 || warn "No se pudo abrir el navegador automáticamente."
else
  info "Abra $APP_URL en su navegador."
fi
