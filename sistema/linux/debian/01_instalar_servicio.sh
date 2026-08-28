#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="PULSIA Inventario Técnico"
SERVICE_NAME="pulsia-inventario"
CADDY_SERVICE_NAME="pulsia-inventario-caddy"
CADDY_SITE="almacen"
BACKEND_HOST="127.0.0.1"
BACKEND_PORT="8080"
HTTP_PORT="80"
HTTPS_PORT="443"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=10
BOOTSTRAP_PYTHON_VERSION="${PULSIA_PYTHON_VERSION:-3.12.10}"
CLIENT_OPENSSL_VERSION="${PULSIA_CLIENT_OPENSSL_VERSION:-3.5.7}"
WINE_SOURCE_FALLBACK_VERSION="${PULSIA_WINE_SOURCE_FALLBACK_VERSION:-11.14}"
MIN_WINE_MAJOR=8
MIN_WINE_MINOR=18
ALLOW_VM_NAT="${PULSIA_ALLOW_VM_NAT:-0}"
VIRT_TYPE="none"
VM_NAT_DETECTED=0

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
PRODUCTION_ROOT="${PULSIA_PROJECT_ROOT:-/almacen}"
VENV_DIR="$PROJECT_ROOT/.venv"
ENV_FILE="$PROJECT_ROOT/.env"
DATA_DIR="$PROJECT_ROOT/data"
LOG_DIR="$PROJECT_ROOT/logs"
BACKUP_DIR="$PROJECT_ROOT/backups"
CERT_DIR="$PROJECT_ROOT/certs"
SYSTEM_CONFIG_DIR="/etc/pulsia-inventario"
CADDYFILE="$SYSTEM_CONFIG_DIR/Caddyfile"
SYSTEMD_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
CADDY_SYSTEMD_FILE="/etc/systemd/system/${CADDY_SERVICE_NAME}.service"
CADDY_DATA_DIR="/var/lib/${CADDY_SERVICE_NAME}"
CADDY_ADMIN_ADDR="127.0.0.1:2020"
CADDY_ADMIN_PORT="2020"
CLIENT_DIR="$PROJECT_ROOT/cliente"
CLIENT_APP_DIR="$CLIENT_DIR/PULSIA_Inventario_Cliente"
CLIENT_APP_CERT_DIR="$CLIENT_APP_DIR/certificados"
APP_CLIENT_OUTPUT_DIR="$PROJECT_ROOT/app cliente"
INSTALL_LOG="$LOG_DIR/instalacion.log"
LOCK_FILE="/var/lock/${SERVICE_NAME}-install.lock"
MANIFEST_FILE="$SYSTEM_CONFIG_DIR/installation.json"
CURRENT_PHASE="preflight"
INSTALL_COMMITTED=0
SERVICE_WAS_ACTIVE=0
CADDY_WAS_ACTIVE=0
CONTINUOUS_WAS_ACTIVE=0
DB_BACKUP=""
VENV_PREVIOUS="$PROJECT_ROOT/.venv.previous"

ok(){ printf '\033[32m[OK]\033[0m %s\n' "$*"; }
info(){ printf '\033[36m[INFO]\033[0m %s\n' "$*"; }
warn(){ printf '\033[33m[AVISO]\033[0m %s\n' "$*"; }
fail(){ printf '\033[31m[ERROR]\033[0m %s\n' "$*" >&2; exit 1; }
phase(){ CURRENT_PHASE="$1"; info "[FASE] $1"; }

on_error(){
  local rc=$? line=${BASH_LINENO[0]:-?} cmd=${BASH_COMMAND:-?}
  trap - ERR
  set +e
  printf '\n\033[31m[ERROR]\033[0m Fallo en línea %s (código %s): %s\n' "$line" "$rc" "$cmd" >&2
  printf '        Fase: %s\n' "$CURRENT_PHASE" >&2
  printf '        Revise el log: %s\n' "$INSTALL_LOG" >&2
  if [[ "${INSTALL_COMMITTED:-0}" != "1" && -d "${VENV_PREVIOUS:-}" ]]; then
    printf '        Intentando rollback de entorno/SQLite previo...\n' >&2
    systemctl stop "$CADDY_SERVICE_NAME" "$SERVICE_NAME" pulsia-inventario-continuous-backup.service >/dev/null 2>&1 || true
    rm -rf "$VENV_DIR"
    mv "$VENV_PREVIOUS" "$VENV_DIR" || true
    if [[ -n "${DB_BACKUP:-}" && -f "$DB_BACKUP" && -f "$DATA_DIR/inventario.sqlite3" ]]; then
      "${PYTHON_BIN:-python3}" - "$DB_BACKUP" "$DATA_DIR/inventario.sqlite3" <<'PYROLLBACK'
import sqlite3,sys
src,dst=sys.argv[1:3]
a=sqlite3.connect(f"file:{src}?mode=ro",uri=True,timeout=10); b=sqlite3.connect(dst,timeout=10)
try:
    a.backup(b,pages=256,sleep=0.05); b.commit()
finally:
    b.close(); a.close()
PYROLLBACK
    fi
    (( SERVICE_WAS_ACTIVE == 1 )) && systemctl start "$SERVICE_NAME" >/dev/null 2>&1 || true
    (( CADDY_WAS_ACTIVE == 1 )) && systemctl start "$CADDY_SERVICE_NAME" >/dev/null 2>&1 || true
    (( CONTINUOUS_WAS_ACTIVE == 1 )) && systemctl start pulsia-inventario-continuous-backup.service >/dev/null 2>&1 || true
    printf '        Rollback automático intentado. Verifique el estado de los servicios.\n' >&2
  fi
  exit "$rc"
}
trap on_error ERR

[[ $EUID -eq 0 ]] || fail "Ejecute: sudo bash \"$0\""
[[ -f "$PROJECT_ROOT/manage.py" ]] || fail "No se encuentra manage.py en $PROJECT_ROOT. El instalador debe permanecer dentro de sistema/linux/debian/."
if [[ "$(readlink -f "$PROJECT_ROOT")" != "$(readlink -m "$PRODUCTION_ROOT")" && "${PULSIA_ALLOW_NONSTANDARD_ROOT:-0}" != "1" ]]; then
  fail "Ruta de producción requerida: $PRODUCTION_ROOT. Mueva el contenido de PULSIA a /almacen o use PULSIA_ALLOW_NONSTANDARD_ROOT=1 únicamente para pruebas."
fi

mkdir -p "$LOG_DIR"
touch "$INSTALL_LOG"
chmod 640 "$INSTALL_LOG" || true
exec > >(tee -a "$INSTALL_LOG") 2>&1

# Evita dos instalaciones simultáneas cuando flock está disponible.
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE"
  flock -n 9 || fail "Ya hay otra instalación/actualización de $APP_NAME en curso."
else
  warn "flock no está disponible; se continúa sin bloqueo de instalación concurrente."
fi

info "$APP_NAME"
info "Raíz detectada dinámicamente: $PROJECT_ROOT"
info "Log: $INSTALL_LOG"
phase "01 Preflight y entorno"
# Peores escenarios: disco insuficiente, reloj incorrecto, clon de VM y proyecto movido.
FREE_KB="$(df -Pk "$PROJECT_ROOT" | awk 'NR==2{print $4}')"
[[ "${FREE_KB:-0}" -ge 2097152 ]] || fail "Espacio insuficiente: se requieren al menos 2 GiB libres antes de modificar el sistema."
(( FREE_KB >= 5242880 )) || warn "Quedan menos de 5 GiB libres en el volumen del proyecto."
(( $(date +%Y) >= 2025 )) || fail "La fecha del sistema parece incorrecta. Corrija reloj/NTP antes de instalar TLS o dependencias."
MACHINE_ID="$(cat /etc/machine-id 2>/dev/null || hostname)"
if [[ -f "$MANIFEST_FILE" ]]; then
  OLD_MACHINE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("machine_id", ""))' "$MANIFEST_FILE" 2>/dev/null || true)"
  OLD_ROOT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("project_root", ""))' "$MANIFEST_FILE" 2>/dev/null || true)"
  [[ -z "$OLD_MACHINE" || "$OLD_MACHINE" == "$MACHINE_ID" || "${PULSIA_ALLOW_CLONE:-0}" == 1 ]] || fail "La instalación parece clonada desde otra VM/equipo. Revise MAC/IP/hostname y use PULSIA_ALLOW_CLONE=1 solo conscientemente."
  [[ -z "$OLD_ROOT" || "$OLD_ROOT" == "$PROJECT_ROOT" ]] || warn "Proyecto movido: $OLD_ROOT -> $PROJECT_ROOT. Las unidades systemd y paths se repararán desde la ruta actual."
fi

phase "02 Sistema operativo y paquetes"
# Debian/Ubuntu soportados. Debian 13 (Trixie) es plataforma objetivo explícita.
[[ -r /etc/os-release ]] || fail "No se puede identificar la distribución Linux."
. /etc/os-release
case "${ID:-}" in
  debian) ;;
  *) fail "Este instalador pertenece a sistema/linux/debian y solo debe ejecutarse en Debian 13. Sistema detectado: ${PRETTY_NAME:-${ID:-desconocida}}." ;;
esac
DEBIAN_MAJOR="${VERSION_ID%%.*}"
[[ "${DEBIAN_MAJOR:-0}" -eq 13 ]] || fail "Debian ${VERSION_ID:-desconocido} detectado. Esta rama está validada para Debian 13 (Trixie)."
info "Sistema detectado: ${PRETTY_NAME:-$ID}"
if [[ "${ID:-}" == debian ]]; then
  DEBIAN_MAJOR="${VERSION_ID%%.*}"
  if [[ "${DEBIAN_MAJOR:-0}" -ge 13 ]]; then
    ok "Debian ${VERSION_ID:-13} detectado: se utilizará Python del sistema (3.13 en Debian 13) cuando esté disponible."
  else
    warn "Debian ${VERSION_ID:-desconocido} detectado. El instalador seguirá siendo conservador y exigirá Python >= 3.10."
  fi
fi

if command -v systemd-detect-virt >/dev/null 2>&1; then
  VIRT_TYPE="$(systemd-detect-virt --vm 2>/dev/null || true)"
  [[ -n "$VIRT_TYPE" ]] || VIRT_TYPE="none"
fi
if [[ "$VIRT_TYPE" != none ]]; then
  info "Máquina virtual detectada: $VIRT_TYPE"
else
  info "No se detecta hipervisor de máquina virtual."
fi

if [[ "${1:-}" == "--diagnostico" ]]; then
  echo "============================================================"
  echo "DIAGNÓSTICO PULSIA INVENTARIO - LINUX"
  echo "Sistema : ${PRETTY_NAME:-$ID}"
  echo "Virtualización: $VIRT_TYPE"
  echo "Proyecto: $PROJECT_ROOT"
  echo "============================================================"
  [[ -f "$PROJECT_ROOT/manage.py" ]] && ok "manage.py localizado." || fail "manage.py no localizado."
  py=""
  for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    resolved="$(command -v "$candidate" 2>/dev/null || true)"
    if [[ -n "$resolved" ]] && "$resolved" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)' >/dev/null 2>&1; then py="$resolved"; break; fi
  done
  if [[ -n "$py" ]]; then ok "Python compatible: $py ($($py --version 2>&1))"; else warn "No hay Python >= 3.10; el instalador intentará instalar Python $BOOTSTRAP_PYTHON_VERSION en paralelo."; fi
  command -v caddy >/dev/null 2>&1 && ok "Caddy: $(command -v caddy)" || info "Caddy no instalado; se instalará si es necesario."
  ss -ltnp 2>/dev/null | grep -E '[:.]443[[:space:]]' && warn "TCP/443 está ocupado." || ok "TCP/443 libre."
  ss -ltnp 2>/dev/null | grep -E '[:.]8080[[:space:]]' && warn "TCP/8080 está ocupado." || ok "TCP/8080 libre."
  ip -o -4 addr show scope global 2>/dev/null | awk '{print "[INFO] Interfaz/IP: "$2" "$4}' || true
  ip route show default 2>/dev/null | awk '{print "[INFO] Gateway: "$3" interfaz "$5; exit}' || true
  if command -v resolvectl >/dev/null 2>&1; then resolvectl dns 2>/dev/null | sed 's/^/[INFO] /' || true; else awk '/^nameserver/ {print "[INFO] DNS: "$2}' /etc/resolv.conf 2>/dev/null || true; fi
  pgrep -afi 'eset|eea|efs' >/dev/null 2>&1 && warn "ESET detectado; puede requerir permitir TCP/443." || true
  exit 0
fi

# Aviso de espacio insuficiente antes de compilar/instalar dependencias.
FREE_KB="$(df -Pk "$PROJECT_ROOT" | awk 'NR==2 {print $4}')"
if [[ "${FREE_KB:-0}" -lt 2097152 ]]; then
  warn "Quedan menos de 2 GiB libres en el volumen del proyecto. La instalación puede necesitar más espacio."
fi

APT_UPDATED=0
APT_FALLBACK=0
APT_FALLBACK_LIST=""
APT_FALLBACK_PARTS=""

cleanup_apt_fallback(){
  [[ -n "$APT_FALLBACK_LIST" ]] && rm -f "$APT_FALLBACK_LIST" || true
  [[ -n "$APT_FALLBACK_PARTS" ]] && rm -rf "$APT_FALLBACK_PARTS" || true
}
trap cleanup_apt_fallback EXIT

apt_update_safe(){
  (( APT_UPDATED == 1 )) && return 0
  local tmp_log
  tmp_log="$(mktemp)"
  info "Actualizando catálogo APT..."
  if apt-get update 2>&1 | tee "$tmp_log"; then
    APT_UPDATED=1
    rm -f "$tmp_log"
    return 0
  fi

  warn "APT tiene al menos un repositorio con errores. No se modificará ni desactivará ningún repositorio de terceros."
  grep -E '^(Err:|W: GPG error:|E: The repository|.*EXPKEYSIG|.*NO_PUBKEY)' "$tmp_log" | sed 's/^/        /' || true
  rm -f "$tmp_log"

  # Reintento sin tocar la configuración persistente: solo fuentes oficiales de Debian/Ubuntu
  # y el repositorio oficial de Caddy si ya existe.
  APT_FALLBACK_LIST="$(mktemp --suffix=.list)"
  APT_FALLBACK_PARTS="$(mktemp -d)"
  : > "$APT_FALLBACK_LIST"

  for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list; do
    [[ -f "$f" ]] || continue
    grep -hE '^[[:space:]]*deb ' "$f" 2>/dev/null | \
      grep -E '(archive\.ubuntu\.com|security\.ubuntu\.com|ports\.ubuntu\.com|deb\.debian\.org|security\.debian\.org|dl\.cloudsmith\.io/public/caddy)' \
      >> "$APT_FALLBACK_LIST" || true
  done
  for f in /etc/apt/sources.list.d/*.sources; do
    [[ -f "$f" ]] || continue
    if grep -Eq '(ubuntu\.com|debian\.org|dl\.cloudsmith\.io/public/caddy)' "$f"; then
      cp "$f" "$APT_FALLBACK_PARTS/"
    fi
  done

  if [[ ! -s "$APT_FALLBACK_LIST" ]] && ! find "$APT_FALLBACK_PARTS" -maxdepth 1 -type f | grep -q .; then
    fail "APT falla y no se pudieron identificar fuentes oficiales seguras para continuar. Corrija APT y vuelva a ejecutar el instalador."
  fi

  info "Reintentando APT temporalmente solo con repositorios oficiales/permitidos..."
  if apt-get \
      -o "Dir::Etc::sourcelist=$APT_FALLBACK_LIST" \
      -o "Dir::Etc::sourceparts=$APT_FALLBACK_PARTS" \
      update; then
    APT_UPDATED=1
    APT_FALLBACK=1
    ok "APT operativo usando temporalmente solo repositorios oficiales/permitidos. Los repositorios con error NO se han cambiado."
    return 0
  fi

  fail "APT continúa fallando incluso con fuentes oficiales. Revise conectividad, DNS, hora del sistema y certificados."
}

apt_install(){
  (($# > 0)) || return 0
  apt_update_safe
  info "Asegurando dependencias del sistema (se solicitan todas, estén o no instaladas): $*"
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "$@"
}

python_is_compatible(){
  local bin="$1"
  [[ -x "$bin" || "$(command -v "$bin" 2>/dev/null || true)" ]] || return 1
  "$bin" -c "import sys; raise SystemExit(0 if sys.version_info >= ($MIN_PYTHON_MAJOR,$MIN_PYTHON_MINOR) else 1)" >/dev/null 2>&1
}

find_compatible_python(){
  local candidate resolved
  for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    resolved="$(command -v "$candidate" 2>/dev/null || true)"
    if [[ -n "$resolved" ]] && python_is_compatible "$resolved"; then
      printf '%s\n' "$resolved"
      return 0
    fi
  done
  return 1
}

python_has_shared_library(){
  local bin="$1"
  [[ -x "$bin" || "$(command -v "$bin" 2>/dev/null || true)" ]] || return 1
  "$bin" - <<'PY' >/dev/null 2>&1
import os, sys, sysconfig
if sys.version_info < (3, 10):
    raise SystemExit(1)
if int(sysconfig.get_config_var("Py_ENABLE_SHARED") or 0) != 1:
    raise SystemExit(2)
libdir = sysconfig.get_config_var("LIBDIR") or ""
ldlib = sysconfig.get_config_var("LDLIBRARY") or ""
if not libdir or not ldlib or not os.path.exists(os.path.join(libdir, ldlib)):
    raise SystemExit(3)
PY
}

find_client_build_python(){
  local candidate resolved
  for candidate in /usr/bin/python3.13 /usr/bin/python3.12 /usr/bin/python3.11 /usr/bin/python3.10 \
                   python3.13 python3.12 python3.11 python3.10 python3; do
    if [[ -x "$candidate" ]]; then
      resolved="$candidate"
    else
      resolved="$(command -v "$candidate" 2>/dev/null || true)"
    fi
    [[ -n "$resolved" ]] || continue
    if python_has_shared_library "$resolved"; then
      printf '%s\n' "$resolved"
      return 0
    fi
  done
  return 1
}


ensure_client_openssl3(){
  local ssl_path crypto_path ver prefix build_dir tarball checksum_url expected actual

  ssl_path="$(ldconfig -p 2>/dev/null | awk '/libssl\.so\.3 /{print $NF; exit}' || true)"
  crypto_path="$(ldconfig -p 2>/dev/null | awk '/libcrypto\.so\.3 /{print $NF; exit}' || true)"
  if [[ -n "$ssl_path" && -n "$crypto_path" && -f "$ssl_path" && -f "$crypto_path" ]]; then
    if [[ "$(dirname "$ssl_path")" == "$(dirname "$crypto_path")" ]]; then
      CLIENT_OPENSSL_LIBDIR="$(dirname "$ssl_path")"
      ok "OpenSSL 3 del sistema disponible para empaquetar: $CLIENT_OPENSSL_LIBDIR"
      return 0
    fi
  fi

  ver="$CLIENT_OPENSSL_VERSION"
  prefix="/opt/pulsia/client-openssl-$ver"
  ssl_path="$(find "$prefix" -type f -name 'libssl.so.3' -print -quit 2>/dev/null || true)"
  crypto_path="$(find "$prefix" -type f -name 'libcrypto.so.3' -print -quit 2>/dev/null || true)"
  if [[ -n "$ssl_path" && -n "$crypto_path" ]]; then
    CLIENT_OPENSSL_LIBDIR="$(dirname "$ssl_path")"
    ok "OpenSSL 3 portable reutilizado: $CLIENT_OPENSSL_LIBDIR"
    return 0
  fi

  warn "El sistema no ofrece libssl.so.3/libcrypto.so.3 (habitual en Ubuntu 20.04)."
  info "Se construirá OpenSSL $ver para incluirlo DENTRO del cliente Linux; no sustituye OpenSSL del sistema."

  apt_install build-essential ca-certificates curl perl
  build_dir="/tmp/pulsia-client-openssl-$ver"
  tarball="/tmp/openssl-$ver.tar.gz"
  checksum_url="https://www.openssl.org/source/openssl-$ver.tar.gz.sha256"

  rm -rf "$prefix" "$build_dir" "$tarball" "$tarball.sha256"
  mkdir -p "$build_dir" "$(dirname "$prefix")"

  curl -fL --retry 5 --retry-delay 3 --connect-timeout 15 \
    "https://www.openssl.org/source/openssl-$ver.tar.gz" -o "$tarball"
  expected="$(curl -fL --retry 5 --retry-delay 3 --connect-timeout 15 "$checksum_url" | awk 'NR==1{print $1}')"
  actual="$(sha256sum "$tarball" | awk '{print $1}')"
  [[ -n "$expected" && "$actual" == "$expected" ]] || \
    fail "La verificación SHA-256 de OpenSSL $ver ha fallado."

  tar -xzf "$tarball" -C "$build_dir" --strip-components=1
  pushd "$build_dir" >/dev/null
  ./Configure linux-x86_64 shared no-module no-legacy no-apps \
    --prefix="$prefix" \
    --openssldir="$prefix/ssl"
  make -j"$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)"
  make install_sw
  popd >/dev/null
  rm -rf "$build_dir" "$tarball"

  ssl_path="$(find "$prefix" -type f -name 'libssl.so.3' -print -quit 2>/dev/null || true)"
  crypto_path="$(find "$prefix" -type f -name 'libcrypto.so.3' -print -quit 2>/dev/null || true)"
  [[ -n "$ssl_path" && -n "$crypto_path" ]] || \
    fail "OpenSSL $ver se compiló pero no se encontraron sus librerías compartidas."

  CLIENT_OPENSSL_LIBDIR="$(dirname "$ssl_path")"
  ok "OpenSSL 3 portable preparado para el cliente: $CLIENT_OPENSSL_LIBDIR"
}

version_ge(){
  # Usage: version_ge CURRENT REQUIRED
  dpkg --compare-versions "$1" ge "$2"
}

wine_version_number(){
  local out="${1:-}"
  out="${out#wine-}"
  out="${out%% *}"
  printf '%s\n' "$out"
}

detect_latest_wine_source_version(){
  local detected=""
  if [[ -n "${PULSIA_WINE_SOURCE_VERSION:-}" ]]; then
    printf '%s\n' "$PULSIA_WINE_SOURCE_VERSION"
    return 0
  fi

  # La primera noticia Wine X.Y Released de la página oficial corresponde a
  # la última release publicada. Si WineHQ cambia el HTML o no hay red,
  # utilizamos la release verificada al crear este instalador.
  detected="$(curl -fsSL --connect-timeout 15 --max-time 30 \
      'https://www.winehq.org/news/1' 2>/dev/null |
      grep -Eo 'Wine [0-9]+\.[0-9]+ Released' |
      head -n1 | awk '{print $2}' || true)"

  if [[ "$detected" =~ ^[0-9]+\.[0-9]+$ ]]; then
    printf '%s\n' "$detected"
  else
    warn "No se pudo detectar la última release de WineHQ; se usará fallback $WINE_SOURCE_FALLBACK_VERSION." >&2
    printf '%s\n' "$WINE_SOURCE_FALLBACK_VERSION"
  fi
}

ensure_private_wine(){
  local ver major minor source_series prefix wine_bin source_url
  local src_dir build_dir tarball current

  ver="$(detect_latest_wine_source_version)"
  major="${ver%%.*}"
  minor="${ver#*.}"
  if [[ "$minor" == "0" ]]; then
    source_series="${major}.0"
  else
    source_series="${major}.x"
  fi

  prefix="/opt/pulsia/wine-private-$ver"
  wine_bin="$prefix/bin/wine"

  if [[ -x "$wine_bin" ]]; then
    current="$("$wine_bin" --version 2>/dev/null || true)"
    current="$(wine_version_number "$current")"
    if [[ -n "$current" ]] && version_ge "$current" "8.18"; then
      PRIVATE_WINE_BIN="$wine_bin"
      ok "Wine privado PULSIA reutilizado: $PRIVATE_WINE_BIN (Wine $current)."
      return 0
    fi
    warn "Wine privado existente no es válido; se reconstruirá."
    rm -rf "$prefix"
  fi

  info "Preparando Wine $ver PRIVADO para PULSIA desde código fuente oficial WineHQ."
  info "No se instalará ni eliminará Wine del sistema y no se usarán paquetes WineHQ APT."

  # Dependencias de compilación/runtime necesarias para nuestro caso:
  # ejecutar Python Windows x64 + pip + PyInstaller bajo X11/Xvfb.
  apt_install \
    build-essential gcc g++ make flex bison pkg-config gcc-mingw-w64-x86-64 \
    ca-certificates curl xz-utils file \
    libx11-dev libxext-dev libxrender-dev libxrandr-dev libxcursor-dev \
    libxi-dev libxinerama-dev libxcomposite-dev libxfixes-dev \
    libfreetype6-dev libfontconfig1-dev libxkbcommon-dev \
    libgnutls28-dev libdbus-1-dev libudev-dev libunwind-dev \
    libasound2-dev libpulse-dev

  src_dir="/tmp/pulsia-wine-src-$ver"
  build_dir="/tmp/pulsia-wine-build-$ver"
  tarball="/tmp/wine-$ver.tar.xz"
  source_url="https://dl.winehq.org/wine/source/$source_series/wine-$ver.tar.xz"

  rm -rf "$src_dir" "$build_dir" "$tarball" "$prefix"
  mkdir -p "$src_dir" "$build_dir" "$(dirname "$prefix")"

  info "Descargando Wine $ver desde $source_url ..."
  curl -fL --retry 5 --retry-delay 3 --connect-timeout 20 \
    "$source_url" -o "$tarball"
  tar -xJf "$tarball" -C "$src_dir" --strip-components=1

  pushd "$build_dir" >/dev/null
  # Solo necesitamos ejecutar binarios Windows x64 para construir el cliente.
  # Un build x86_64 evita depender de la cadena completa i386 de Ubuntu 20.04.
  "$src_dir/configure" \
    --prefix="$prefix" \
    --enable-win64
  make -j"$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)"
  make install
  popd >/dev/null

  rm -rf "$src_dir" "$build_dir" "$tarball"

  [[ -x "$wine_bin" ]] || fail "Wine $ver se compiló pero no existe $wine_bin."
  current="$("$wine_bin" --version 2>/dev/null || true)"
  current="$(wine_version_number "$current")"
  [[ -n "$current" ]] || fail "Wine privado compilado pero no responde a --version."
  version_ge "$current" "8.18" || \
    fail "Wine privado $current no cumple el mínimo 8.18 requerido."

  PRIVATE_WINE_BIN="$wine_bin"
  mkdir -p "$SYSTEM_CONFIG_DIR"
  {
    printf 'version=%s\n' "$current"
    printf 'prefix=%s\n' "$prefix"
    printf 'wine_bin=%s\n' "$wine_bin"
    printf 'source=%s\n' "$source_url"
  } > "$SYSTEM_CONFIG_DIR/private-wine-installed-by-pulsia"

  ok "Wine privado PULSIA listo: $PRIVATE_WINE_BIN (Wine $current)."
}

install_python_from_source(){
  local ver="$BOOTSTRAP_PYTHON_VERSION"
  local mm="${ver%.*}"
  local prefix="/opt/pulsia/python-$ver"
  local bin="$prefix/bin/python$mm"
  local build_dir="/tmp/pulsia-python-$ver"
  local tarball="/tmp/Python-$ver.tgz"

  if [[ -x "$bin" ]] && python_is_compatible "$bin"; then
    PYTHON_BIN="$bin"
    return 0
  fi

  warn "El sistema no dispone de Python >= $MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR. Se instalará Python $ver EN PARALELO en $prefix."
  warn "No se sustituirá /usr/bin/python3 ni se eliminará el Python del sistema."

  apt_install \
    build-essential ca-certificates curl xz-utils \
    libssl-dev zlib1g-dev libncurses-dev \
    libreadline-dev libsqlite3-dev libgdbm-dev libdb-dev \
    libbz2-dev libexpat1-dev liblzma-dev tk-dev libffi-dev uuid-dev

  rm -rf "$build_dir"
  mkdir -p "$build_dir"
  info "Descargando Python $ver desde python.org..."
  curl -fL --retry 5 --retry-delay 3 --connect-timeout 15 \
    "https://www.python.org/ftp/python/$ver/Python-$ver.tgz" -o "$tarball"
  tar -xzf "$tarball" -C "$build_dir" --strip-components=1
  pushd "$build_dir" >/dev/null
  ./configure --prefix="$prefix" --with-ensurepip=install
  make -j"$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)"
  make altinstall
  popd >/dev/null
  rm -rf "$build_dir" "$tarball"

  [[ -x "$bin" ]] || fail "Python $ver se compiló pero no se encontró $bin."
  python_is_compatible "$bin" || fail "La instalación paralela de Python no cumple la versión mínima requerida."
  PYTHON_BIN="$bin"
}

# Dependencias del servicio. Se solicitan SIEMPRE a APT para no asumir que
# una imagen/minimal install trae ningún componente previamente instalado.
apt_install   ca-certificates curl openssl iproute2 procps sudo   python3 python3-venv python3-pip python3-dev   build-essential pkg-config   libssl-dev libffi-dev zlib1g-dev libjpeg-dev   libpq5 libpq-dev

# Python del sistema es la primera opción. Si no cumple >=3.10, el instalador
# conserva el fallback de compilación privada.

PYTHON_BIN="$(find_compatible_python || true)"
if [[ -z "$PYTHON_BIN" ]]; then
  install_python_from_source
fi
PYTHON_VERSION="$($PYTHON_BIN -c 'import platform; print(platform.python_version())')"
ok "Python compatible: $PYTHON_BIN ($PYTHON_VERSION)"

phase "03 Parada segura y snapshot previo"
# En actualizaciones, detener primero todos los procesos que pueden usar código o SQLite.
systemctl is-active --quiet "$SERVICE_NAME" && SERVICE_WAS_ACTIVE=1 || true
systemctl is-active --quiet "$CADDY_SERVICE_NAME" && CADDY_WAS_ACTIVE=1 || true
systemctl is-active --quiet pulsia-inventario-continuous-backup.service && CONTINUOUS_WAS_ACTIVE=1 || true
for unit in "$CADDY_SERVICE_NAME" "$SERVICE_NAME" pulsia-inventario-continuous-backup.service; do
  systemctl stop "$unit" >/dev/null 2>&1 || true
done
# El servidor de producción tiene un único Caddy y PULSIA es su propietario.
systemctl stop caddy.service >/dev/null 2>&1 || true
mkdir -p "$BACKUP_DIR"
if [[ -f "$DATA_DIR/inventario.sqlite3" ]]; then
  DB_BACKUP="$BACKUP_DIR/pre_upgrade_$(date +%Y%m%d_%H%M%S).sqlite3"
  "$PYTHON_BIN" - "$DATA_DIR/inventario.sqlite3" "$DB_BACKUP" <<'PYSQLBACKUP'
import sqlite3, sys
src,dst=sys.argv[1:3]
a=sqlite3.connect(f"file:{src}?mode=ro",uri=True,timeout=10)
b=sqlite3.connect(dst,timeout=10)
try:
    a.execute("PRAGMA busy_timeout=10000")
    a.backup(b,pages=256,sleep=0.05)
    check=b.execute("PRAGMA quick_check").fetchone()[0]
    if check!="ok": raise SystemExit("quick_check del snapshot previo: "+str(check))
    b.commit()
finally:
    b.close(); a.close()
PYSQLBACKUP
  ok "Snapshot SQLite consistente previo a la actualización: $DB_BACKUP"
fi

phase "04 Python y entorno virtual"
# Instalación determinista: el entorno virtual se recrea SIEMPRE. No se asume
# que un .venv previo esté completo, sano o construido con el Python correcto.
rm -rf "$VENV_PREVIOUS"
if [[ -d "$VENV_DIR" ]]; then
  info "Conservando .venv anterior temporalmente para rollback..."
  mv "$VENV_DIR" "$VENV_PREVIOUS"
fi

"$PYTHON_BIN" -m venv "$VENV_DIR" || {
  # ensurepip/venv puede faltar en instalaciones mínimas: se vuelve a solicitar
  # explícitamente y se reintenta.
  apt_install python3-venv python3-pip
  "$PYTHON_BIN" -m venv "$VENV_DIR"
}
[[ -x "$VENV_DIR/bin/python" ]] || fail "No se pudo crear el entorno virtual."
ok "Entorno virtual nuevo: $($VENV_DIR/bin/python --version 2>&1)."

phase "04 Dependencias Python"
SERVER_BASE_REQ="$PROJECT_ROOT/requirements/servidor-base.txt"
[[ -f "$SERVER_BASE_REQ" ]] || fail "Falta $SERVER_BASE_REQ"

# No se da por hecho que pip/setuptools/wheel existan o estén actualizados.
"$VENV_DIR/bin/python" -m ensurepip --upgrade >/dev/null 2>&1 || true
"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel packaging \
  --retries 5 --timeout 60

# Primero las dependencias no conflictivas.
"$VENV_DIR/bin/python" -m pip install --upgrade --prefer-binary \
  -r "$SERVER_BASE_REQ" --retries 5 --timeout 60

# Psycopg es la dependencia con mayor sensibilidad a versión de Python/plataforma.
# Preferimos wheel binario dentro de una familia compatible; si el índice/mirror no
# ofrece ese wheel, usamos implementación Python + libpq del sistema.
if "$VENV_DIR/bin/python" -m pip install --upgrade --prefer-binary \
    "psycopg[binary]>=3.3.4,<4" --retries 5 --timeout 60; then
  ok "psycopg[binary] instalado con wheel compatible."
else
  warn "No hay wheel psycopg-binary compatible en el índice actual. Aplicando fallback con libpq."
  apt_install libpq5 libpq-dev
  "$VENV_DIR/bin/python" -m pip install --upgrade \
    "psycopg>=3.3.4,<4" --retries 5 --timeout 60
fi

"$VENV_DIR/bin/python" -m pip check || fail "pip check detectó dependencias incompatibles."

# Verificación funcional mínima antes de tocar migraciones, Caddy o servicios.
"$VENV_DIR/bin/python" - <<'PYDEPS'
import importlib
mods = [
    "django", "waitress", "psycopg", "openpyxl", "reportlab",
    "dotenv", "whitenoise", "PIL", "dns",
]
bad=[]
for mod in mods:
    try:
        importlib.import_module(mod)
    except Exception as exc:
        bad.append(f"{mod}: {exc}")
if bad:
    raise SystemExit("Dependencias Python no utilizables:\n  " + "\n  ".join(bad))
print("[OK] Imports críticos Python verificados.")
PYDEPS

mkdir -p "$LOG_DIR"
{
  echo "GENERATED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "OS=${PRETTY_NAME:-$ID}"
  echo "ARCH=$(uname -m)"
  echo "PYTHON=$($VENV_DIR/bin/python -c 'import platform; print(platform.python_version())')"
  "$VENV_DIR/bin/python" -m pip freeze
} > "$LOG_DIR/python-dependencies-resolved.txt"
ok "Dependencias resueltas registradas en $LOG_DIR/python-dependencies-resolved.txt"

mkdir -p "$DATA_DIR"

phase "05 Red, IP y DNS"
# ---------------------------------------------------------------------------
# Red del servidor: conservar DHCP por defecto y detectar la configuración actual.
# La opción preferente es reservar la IP/MAC actual en el servidor DHCP.
# Solo PULSIA_CONFIGURE_STATIC_IP=1 convierte explícitamente la IP actual en
# configuración estática local; nunca se elige una IP al azar.
# ---------------------------------------------------------------------------
NETWORK_HELPER="$PROJECT_ROOT/sistema/common/network_dns.py"
DNS_HOST="${PULSIA_DNS_HOST:-almacen}"
CONFIGURE_STATIC_IP="${PULSIA_CONFIGURE_STATIC_IP:-0}"
UPDATE_CORPORATE_DNS="${PULSIA_DNS_UPDATE:-1}"
NETWORK_IFACE="$(ip route show default 2>/dev/null | awk '/default/ {print $5; exit}')"
NETWORK_GATEWAY="$(ip route show default 2>/dev/null | awk '/default/ {print $3; exit}')"
NETWORK_CIDR=""
NETWORK_IP=""
NETWORK_DNS=()
NETWORK_ZONE=""

if [[ -n "$NETWORK_IFACE" ]]; then
  NETWORK_CIDR="$(ip -o -4 addr show dev "$NETWORK_IFACE" scope global 2>/dev/null | awk '{print $4; exit}')"
  NETWORK_IP="${NETWORK_CIDR%%/*}"
  if command -v resolvectl >/dev/null 2>&1; then
    while IFS= read -r d; do [[ "$d" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] && [[ "$d" != 127.* ]] && NETWORK_DNS+=("$d"); done < <(resolvectl dns "$NETWORK_IFACE" 2>/dev/null | sed 's/.*: //' | tr ' ' '\n')
    NETWORK_ZONE="$(resolvectl domain "$NETWORK_IFACE" 2>/dev/null | sed 's/.*: //' | tr ' ' '\n' | grep -v '^~\.$' | grep -v '^~' | head -n1 || true)"
  fi
  if ((${#NETWORK_DNS[@]} == 0)); then
    while IFS= read -r d; do [[ "$d" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] && [[ "$d" != 127.* ]] && NETWORK_DNS+=("$d"); done < <(awk '/^nameserver[[:space:]]+/ {print $2}' /etc/resolv.conf 2>/dev/null)
  fi
  [[ -n "$NETWORK_ZONE" ]] || NETWORK_ZONE="$(awk '/^(search|domain)[[:space:]]+/ {print $2; exit}' /etc/resolv.conf 2>/dev/null || true)"
  [[ -n "$NETWORK_ZONE" ]] || NETWORK_ZONE="$(hostname -d 2>/dev/null || true)"
  info "Interfaz LAN: $NETWORK_IFACE; IP: ${NETWORK_CIDR:-desconocida}; gateway: ${NETWORK_GATEWAY:-desconocido}; DNS: ${NETWORK_DNS[*]:-no detectado}; zona: ${NETWORK_ZONE:-no detectada}"
fi

# VirtualBox en NAT usa por defecto 10.0.2.0/24 con gateway 10.0.2.2. Esa red
# no permite que otros equipos de la LAN lleguen directamente al servidor.
if [[ "$VIRT_TYPE" =~ ^(oracle|vbox|virtualbox)$ ]] && [[ "${NETWORK_IP:-}" == 10.0.2.* ]] && [[ "${NETWORK_GATEWAY:-}" == 10.0.2.2 ]]; then
  VM_NAT_DETECTED=1
  warn "Se detecta VirtualBox con el patrón de red NAT por defecto ($NETWORK_IP, gateway $NETWORK_GATEWAY)."
  warn "Para un servidor LAN configure VirtualBox -> Red -> Adaptador puente y vuelva a ejecutar el instalador."
  if [[ "$ALLOW_VM_NAT" != 1 ]]; then
    fail "La VM está en NAT y no será accesible directamente desde la LAN. Use adaptador puente o PULSIA_ALLOW_VM_NAT=1 si ha configurado redirección de puertos conscientemente."
  fi
fi

# Si el resolver local solo muestra 127.0.0.53 u otro stub, descubrir antes de
# desactivar DHCP qué DNS reales responden en la subred.
if ((${#NETWORK_DNS[@]} == 0)) && [[ -n "$NETWORK_CIDR" && -f "$NETWORK_HELPER" ]]; then
  SCAN_JSON="$($VENV_DIR/bin/python "$NETWORK_HELPER" scan --cidr "$NETWORK_CIDR" 2>/dev/null || true)"
  if [[ -n "$SCAN_JSON" ]]; then
    while IFS= read -r d; do [[ -n "$d" ]] && NETWORK_DNS+=("$d"); done < <("$VENV_DIR/bin/python" -c 'import json,sys; [print(x) for x in json.load(sys.stdin).get("dns_servers",[])]' <<<"$SCAN_JSON" 2>/dev/null || true)
  fi
fi

configure_static_linux(){
  [[ "$VM_NAT_DETECTED" != 1 ]] || { warn "No se fija como estática una IP NAT de la VM."; return 0; }
  [[ "$CONFIGURE_STATIC_IP" == 1 ]] || { info "DHCP se conserva por defecto. Use la reserva DHCP por MAC/IP desde la app o defina PULSIA_CONFIGURE_STATIC_IP=1 para fijar localmente la IP actual."; return 0; }
  [[ -n "$NETWORK_IFACE" && -n "$NETWORK_CIDR" && -n "$NETWORK_GATEWAY" ]] || { warn "No se puede fijar IP: faltan interfaz/IP/gateway."; return 0; }
  ((${#NETWORK_DNS[@]} > 0)) || { warn "No se encontró un DNS real antes de fijar la IP; por seguridad se conserva DHCP para no dejar el servidor sin resolución DNS."; return 0; }
  local backup="$DATA_DIR/network-backup-linux-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$backup"
  ip addr show dev "$NETWORK_IFACE" > "$backup/ip-addr.txt" || true
  ip route show > "$backup/ip-route.txt" || true
  cp -a /etc/resolv.conf "$backup/resolv.conf" 2>/dev/null || true

  if command -v nmcli >/dev/null 2>&1 && systemctl is-active --quiet NetworkManager 2>/dev/null; then
    local conn method dns_csv
    conn="$(nmcli -g GENERAL.CONNECTION device show "$NETWORK_IFACE" 2>/dev/null | head -n1)"
    [[ -n "$conn" && "$conn" != -- ]] || { warn "NetworkManager activo pero no se pudo identificar la conexión; no se cambia la IP."; return 0; }
    method="$(nmcli -g ipv4.method connection show "$conn" 2>/dev/null || true)"
    if [[ "$method" == manual ]]; then ok "La interfaz $NETWORK_IFACE ya usa IPv4 manual/estática."; return 0; fi
    dns_csv="$(IFS=,; echo "${NETWORK_DNS[*]}")"
    info "Fijando la IP actual $NETWORK_CIDR como estática mediante NetworkManager..."
    nmcli connection modify "$conn" ipv4.method manual ipv4.addresses "$NETWORK_CIDR" ipv4.gateway "$NETWORK_GATEWAY" ipv4.ignore-auto-dns yes
    [[ -n "$dns_csv" ]] && nmcli connection modify "$conn" ipv4.dns "$dns_csv"
    if ! nmcli connection up "$conn" >/dev/null 2>&1 || ! ip -o -4 addr show dev "$NETWORK_IFACE" | grep -q "$NETWORK_CIDR"; then
      warn "La configuración estática no validó. Restaurando DHCP en NetworkManager."
      nmcli connection modify "$conn" ipv4.method auto ipv4.addresses "" ipv4.gateway "" ipv4.dns "" ipv4.ignore-auto-dns no || true
      nmcli connection up "$conn" >/dev/null 2>&1 || true
      return 0
    fi
    ok "IP actual fijada como estática mediante NetworkManager."
    return 0
  fi

  if command -v netplan >/dev/null 2>&1 && grep -RqsE 'dhcp4:[[:space:]]*true' /etc/netplan 2>/dev/null; then
    local np='/etc/netplan/99-pulsia-inventario-static.yaml' dns_yaml=''
    tar -czf "$backup/netplan.tgz" /etc/netplan 2>/dev/null || true
    if ((${#NETWORK_DNS[@]})); then dns_yaml="[$(IFS=,; echo "${NETWORK_DNS[*]}")]"; else dns_yaml='[]'; fi
    cat > "$np" <<EOFNET
network:
  version: 2
  ethernets:
    $NETWORK_IFACE:
      dhcp4: false
      addresses: [$NETWORK_CIDR]
      routes:
        - to: default
          via: $NETWORK_GATEWAY
      nameservers:
        addresses: $dns_yaml
EOFNET
    chmod 600 "$np"
    info "Fijando la IP actual $NETWORK_CIDR mediante Netplan..."
    if netplan generate >/dev/null 2>&1 && netplan apply >/dev/null 2>&1 && sleep 2 && ip -o -4 addr show dev "$NETWORK_IFACE" | grep -q "$NETWORK_CIDR"; then
      ok "IP actual fijada como estática mediante Netplan."
      return 0
    fi
    warn "Netplan no validó la configuración. Restaurando configuración previa."
    rm -f "$np"
    if [[ -f "$backup/netplan.tgz" ]]; then tar -xzf "$backup/netplan.tgz" -C / >/dev/null 2>&1 || true; fi
    netplan apply >/dev/null 2>&1 || true
    return 0
  fi

  # Debian Server suele usar ifupdown (/etc/network/interfaces). Se cambia
  # únicamente el stanza DHCP de la interfaz actual y se valida con ifquery.
  if command -v ifquery >/dev/null 2>&1; then
    local iffile mask tmpfile
    iffile="$(grep -RslE "^[[:space:]]*iface[[:space:]]+$NETWORK_IFACE[[:space:]]+inet[[:space:]]+dhcp([[:space:]]|$)" /etc/network/interfaces /etc/network/interfaces.d 2>/dev/null | head -n1 || true)"
    if [[ -n "$iffile" && -f "$iffile" ]]; then
      cp -a "$iffile" "$backup/$(basename "$iffile").bak"
      mask="$($VENV_DIR/bin/python - "$NETWORK_CIDR" <<'PYMASK'
import ipaddress, sys
print(ipaddress.ip_interface(sys.argv[1]).netmask)
PYMASK
)"
      tmpfile="$(mktemp)"
      "$VENV_DIR/bin/python" - "$iffile" "$tmpfile" "$NETWORK_IFACE" "$NETWORK_IP" "$mask" "$NETWORK_GATEWAY" "${NETWORK_DNS[*]}" <<'PYIF'
import re, sys
src,dst,iface,addr,mask,gw,dns=sys.argv[1:]
lines=open(src,encoding='utf-8',errors='replace').read().splitlines()
out=[]; replaced=False; i=0
pat=re.compile(r'^\s*iface\s+'+re.escape(iface)+r'\s+inet\s+dhcp(?:\s|$)')
while i < len(lines):
    line=lines[i]
    if not replaced and pat.match(line):
        indent=line[:len(line)-len(line.lstrip())]
        out.append(f'{indent}iface {iface} inet static')
        out.append(f'{indent}    address {addr}')
        out.append(f'{indent}    netmask {mask}')
        out.append(f'{indent}    gateway {gw}')
        if dns.strip(): out.append(f'{indent}    dns-nameservers {dns}')
        replaced=True; i += 1
        # Conservar opciones del stanza salvo parámetros de direccionamiento DHCP.
        while i < len(lines) and (lines[i].startswith(' ') or lines[i].startswith('\t')):
            if not re.match(r'^\s*(address|netmask|gateway|dns-nameservers)\b', lines[i]): out.append(lines[i])
            i += 1
        continue
    out.append(line); i += 1
if not replaced: raise SystemExit(2)
open(dst,'w',encoding='utf-8').write('\n'.join(out)+'\n')
PYIF
      cp "$tmpfile" "$iffile"
      rm -f "$tmpfile"
      if ifquery "$NETWORK_IFACE" >/dev/null 2>&1; then
        ok "IP actual preparada como estática mediante ifupdown para el próximo arranque (sin cortar la conexión actual)."
        return 0
      fi
      warn "La configuración ifupdown no validó; restaurando el fichero original."
      cp "$backup/$(basename "$iffile").bak" "$iffile"
      return 0
    fi
  fi

  warn "No se encontró un gestor de red soportado para convertir automáticamente la IP en estática. Se conserva la red actual sin cambios; use preferentemente una reserva DHCP de la MAC de la VM."
}

configure_static_linux

# Redetectar tras fijar la IP.
NETWORK_CIDR="$(ip -o -4 addr show dev "$NETWORK_IFACE" scope global 2>/dev/null | awk '{print $4; exit}')"
NETWORK_IP="${NETWORK_CIDR%%/*}"

DNS_SERVER="${PULSIA_DNS_SERVER:-${NETWORK_DNS[0]:-}}"
DNS_ZONE="${PULSIA_DNS_ZONE:-$NETWORK_ZONE}"
DNS_TSIG_KEY="${PULSIA_DNS_TSIG_KEY_FILE:-$SYSTEM_CONFIG_DIR/dns-update.key}"

configure_corporate_dns_linux(){
  [[ "$VM_NAT_DETECTED" != 1 ]] || { warn "No se actualiza DNS corporativo con una IP NAT de VirtualBox."; return 0; }
  [[ "$UPDATE_CORPORATE_DNS" != 0 ]] || { info "Actualización DNS corporativa desactivada por PULSIA_DNS_UPDATE=0."; return 0; }
  [[ -n "$DNS_SERVER" && -n "$DNS_ZONE" && -n "$NETWORK_IP" ]] || { warn "No se pudo determinar DNS, zona e IP simultáneamente. Se usará hosts/paquete cliente como fallback."; return 0; }
  info "DNS corporativo detectado: $DNS_SERVER; registro solicitado: $DNS_HOST.$DNS_ZONE -> $NETWORK_IP"
  if [[ -f "$DNS_TSIG_KEY" ]]; then
    if "$VENV_DIR/bin/python" "$NETWORK_HELPER" update --server "$DNS_SERVER" --zone "$DNS_ZONE" --host "$DNS_HOST" --address "$NETWORK_IP" --key-file "$DNS_TSIG_KEY" >/dev/null; then
      apt_install dnsutils
      sleep 1
      RESOLVED="$(dig +short @"$DNS_SERVER" "$DNS_HOST.$DNS_ZONE" A 2>/dev/null | tail -n1)"
      if [[ "$RESOLVED" == "$NETWORK_IP" ]]; then ok "DNS actualizado y verificado: $DNS_HOST.$DNS_ZONE -> $NETWORK_IP"; else warn "El DNS respondió '$RESOLVED' después de la actualización."; fi
    else
      warn "El DNS rechazó la actualización RFC2136/TSIG. Se mantiene el fallback por hosts/paquete cliente."
    fi
  else
    warn "DNS encontrado pero no existe una clave TSIG autorizada en $DNS_TSIG_KEY. Por seguridad no se hacen actualizaciones DNS anónimas."
    cat > "$DATA_DIR/dns-registro-pendiente.txt" <<EOFDNS
DNS_SERVER=$DNS_SERVER
DNS_ZONE=$DNS_ZONE
DNS_HOST=$DNS_HOST
DNS_IP=$NETWORK_IP
EOFDNS
  fi
}

configure_corporate_dns_linux

phase "06 Caddy, HTTPS y servicios"
ensure_caddy(){
  if command -v caddy >/dev/null 2>&1; then
    ok "Caddy ya instalado: $(command -v caddy)"
    return 0
  fi

  info "Caddy no está instalado. Intentando paquete disponible en APT..."
  apt_update_safe
  if apt-cache show caddy >/dev/null 2>&1; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y caddy || true
  fi
  command -v caddy >/dev/null 2>&1 && return 0

  info "Añadiendo el repositorio oficial estable de Caddy."
  apt_install debian-keyring debian-archive-keyring apt-transport-https gpg
  curl -1sLf --retry 5 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf --retry 5 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    > /etc/apt/sources.list.d/caddy-stable.list
  chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list
  APT_UPDATED=0
  apt_update_safe
  DEBIAN_FRONTEND=noninteractive apt-get install -y caddy
  command -v caddy >/dev/null 2>&1 || fail "No se pudo instalar Caddy. Revise conectividad/repositorios y vuelva a ejecutar este mismo script."
}
ensure_caddy

mkdir -p "$DATA_DIR" "$LOG_DIR" "$BACKUP_DIR" "$CERT_DIR" "$CLIENT_DIR" "$CLIENT_APP_DIR" "$CLIENT_APP_CERT_DIR" "$SYSTEM_CONFIG_DIR" "$CADDY_DATA_DIR"
chmod 750 "$DATA_DIR" "$LOG_DIR" "$BACKUP_DIR" "$CERT_DIR" || true
chmod 755 "$SYSTEM_CONFIG_DIR" "$CADDY_DATA_DIR" || true

if [[ ! -f "$ENV_FILE" ]]; then
  SECRET="$($VENV_DIR/bin/python - <<'PY'
import secrets
print(secrets.token_urlsafe(64))
PY
)"
  cat > "$ENV_FILE" <<ENVEOF
DJANGO_SECRET_KEY=$SECRET
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=almacen,pizarra,localhost,127.0.0.1,${NETWORK_IP:-127.0.0.1}
DJANGO_CSRF_TRUSTED_ORIGINS=https://almacen,https://pizarra,https://127.0.0.1,https://${NETWORK_IP:-127.0.0.1}
DJANGO_HTTPS=true
DATABASE_URL=sqlite:///data/inventario.sqlite3
INVENTORY_BIND=$BACKEND_HOST
INVENTORY_PORT=$BACKEND_PORT
ENVEOF
  chmod 600 "$ENV_FILE"
  ok ".env creado con secreto aleatorio."
else
  ok ".env existente conservado. Se adapta el acceso web LAN por IP sin reemplazar secretos ni credenciales."
  sed -i -E 's/^INVENTORY_BIND=.*/INVENTORY_BIND=127.0.0.1/' "$ENV_FILE" || true
  grep -q '^INVENTORY_BIND=' "$ENV_FILE" || echo 'INVENTORY_BIND=127.0.0.1' >> "$ENV_FILE"
  sed -i -E 's/^INVENTORY_PORT=.*/INVENTORY_PORT=8080/' "$ENV_FILE" || true
  grep -q '^INVENTORY_PORT=' "$ENV_FILE" || echo 'INVENTORY_PORT=8080' >> "$ENV_FILE"
  sed -i -E "s/^DJANGO_ALLOWED_HOSTS=.*/DJANGO_ALLOWED_HOSTS=almacen,pizarra,localhost,127.0.0.1,${NETWORK_IP:-127.0.0.1}/" "$ENV_FILE" || true
  grep -q '^DJANGO_ALLOWED_HOSTS=' "$ENV_FILE" || echo "DJANGO_ALLOWED_HOSTS=almacen,pizarra,localhost,127.0.0.1,${NETWORK_IP:-127.0.0.1}" >> "$ENV_FILE"
  sed -i -E 's/^DJANGO_HTTPS=.*/DJANGO_HTTPS=true/' "$ENV_FILE" || true
  grep -q '^DJANGO_HTTPS=' "$ENV_FILE" || echo 'DJANGO_HTTPS=true' >> "$ENV_FILE"
  sed -i -E "s#^DJANGO_CSRF_TRUSTED_ORIGINS=.*#DJANGO_CSRF_TRUSTED_ORIGINS=https://almacen,https://pizarra,https://127.0.0.1,https://${NETWORK_IP:-127.0.0.1}#" "$ENV_FILE" || true
  grep -q '^DJANGO_CSRF_TRUSTED_ORIGINS=' "$ENV_FILE" || echo "DJANGO_CSRF_TRUSTED_ORIGINS=https://almacen,https://pizarra,https://127.0.0.1,https://${NETWORK_IP:-127.0.0.1}" >> "$ENV_FILE"
fi

cd "$PROJECT_ROOT"
"$VENV_DIR/bin/python" manage.py check
"$VENV_DIR/bin/python" manage.py migrate --noinput
"$VENV_DIR/bin/python" manage.py collectstatic --noinput


RUN_USER="${SUDO_USER:-root}"
id "$RUN_USER" >/dev/null 2>&1 || RUN_USER=root
RUN_GROUP="$(id -gn "$RUN_USER")"
install -d -o "$RUN_USER" -g "$RUN_GROUP" -m 0750 /var/lib/pulsia-inventario/local-backup
install -d -o "$RUN_USER" -g "$RUN_GROUP" -m 0750 /almacen/backups
# Servicio privilegiado mínimo para configurar exclusivamente el disco secundario de backup.
STORAGE_ADMIN_DIR="/usr/local/lib/pulsia-inventario"
STORAGE_ADMIN_SCRIPT="$STORAGE_ADMIN_DIR/storage_admin.py"
STORAGE_ADMIN_SERVICE="/etc/systemd/system/pulsia-inventario-storage-admin.service"
install -d -m 0755 "$STORAGE_ADMIN_DIR"
install -m 0755 "$SCRIPT_DIR/storage_admin_daemon.py" "$STORAGE_ADMIN_SCRIPT"
cat > "$STORAGE_ADMIN_SERVICE" <<EOF_STORAGE
[Unit]
Description=PULSIA Inventario - administrador local de disco de backup
After=local-fs.target dbus.service

[Service]
Type=simple
User=root
Group=root
Environment=PULSIA_APP_USER=$RUN_USER
Environment=PULSIA_APP_GROUP=$RUN_GROUP
ExecStart=/usr/bin/python3 $STORAGE_ADMIN_SCRIPT
Restart=on-failure
RestartSec=2
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/etc/fstab /var/lib/pulsia-inventario /mnt/pulsia-backup /run/pulsia-inventario /almacen/backups
ProtectHome=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF_STORAGE
systemctl daemon-reload
systemctl enable --now pulsia-inventario-storage-admin.service
ok "Servicio seguro de configuración del disco de backup instalado."

# Servicio de copia SQLite casi continua al disco secundario seleccionado por UUID.
CONTINUOUS_SCRIPT="$STORAGE_ADMIN_DIR/continuous_backup.py"
CONTINUOUS_SERVICE="/etc/systemd/system/pulsia-inventario-continuous-backup.service"
install -m 0755 "$SCRIPT_DIR/continuous_backup_daemon.py" "$CONTINUOUS_SCRIPT"
install -d -o "$RUN_USER" -g "$RUN_GROUP" -m 0750 /var/lib/pulsia-inventario/continuous-backup
cat > "$CONTINUOUS_SERVICE" <<EOF_CONTINUOUS
[Unit]
Description=PULSIA Inventario - copia continua SQLite
After=pulsia-inventario-storage-admin.service local-fs.target
Requires=pulsia-inventario-storage-admin.service

[Service]
Type=simple
User=$RUN_USER
Group=$RUN_GROUP
Environment=PULSIA_DB_PATH=/almacen/data/inventario.sqlite3
Environment=PULSIA_CONTINUOUS_BACKUP_INTERVAL=1.0
ExecStart=/usr/bin/python3 $CONTINUOUS_SCRIPT
Restart=always
RestartSec=2
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/mnt/pulsia-backup /var/lib/pulsia-inventario/continuous-backup /var/lib/pulsia-inventario/local-backup /almacen/backups
ReadOnlyPaths=/almacen/data
ProtectHome=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF_CONTINUOUS
systemctl daemon-reload
systemctl enable --now pulsia-inventario-continuous-backup.service
ok "Servicio de copia continua SQLite instalado (detección de cambios cada ~1 s)."
chown "$RUN_USER:$RUN_GROUP" "$ENV_FILE" || true
chown -R "$RUN_USER:$RUN_GROUP" "$DATA_DIR" "$LOG_DIR" "$BACKUP_DIR" "$CERT_DIR" || true
chmod 600 "$ENV_FILE" || true

# FASE 00: saneamiento de restos de instalaciones anteriores.
# En este servidor dedicado, cualquier proceso Caddy que compita por 443/2019/2020
# se considera residual y se detiene. No se toca nginx/apache/HAProxy u otro software.
# Python solo se finaliza cuando se identifica claramente como Waitress/PULSIA.
cleanup_previous_runtime(){
  info "FASE 00 - Saneando instalaciones Caddy/PULSIA anteriores..."

  systemctl stop "$SERVICE_NAME" >/dev/null 2>&1 || true
  systemctl stop "$CADDY_SERVICE_NAME" >/dev/null 2>&1 || true

  # Retirar unidades Caddy antiguas distintas del servicio dedicado PULSIA.
  while IFS= read -r unit; do
    [[ -z "$unit" ]] && continue
    [[ "$unit" == "$CADDY_SERVICE_NAME.service" ]] && continue
    warn "Servicio Caddy residual detectado: $unit. Se detendra y deshabilitara."
    systemctl stop "$unit" >/dev/null 2>&1 || true
    systemctl disable "$unit" >/dev/null 2>&1 || true
  done < <(systemctl list-unit-files --type=service --no-legend 2>/dev/null | awk '{print $1}' | grep -Ei 'caddy.*\.service$' || true)

  # Cualquier caddy que siga vivo puede conservar sockets aunque su servicio haya caido.
  while IFS= read -r pid; do
    [[ -n "$pid" ]] || continue
    cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
    warn "Finalizando Caddy residual PID $pid ${cmd:+| $cmd}"
    kill "$pid" >/dev/null 2>&1 || true
    sleep 0.2
    kill -9 "$pid" >/dev/null 2>&1 || true
  done < <(pgrep -x caddy 2>/dev/null || true)

  # Backend PULSIA residual: solo procesos Python en 8080 y con Waitress/proyecto PULSIA.
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

  sleep 1
  for port in 80 443 8080 2019 2020; do
    if ss -ltnp 2>/dev/null | awk -v p=":$port" '$4 ~ p"$" {found=1} END{exit !found}'; then
      warn "TCP/$port sigue ocupado tras el saneamiento: $(ss -ltnp 2>/dev/null | awk -v p=":$port" '$4 ~ p"$" {printf "%s ",$0}')"
    else
      ok "TCP/$port libre tras saneamiento."
    fi
  done
}
cleanup_previous_runtime

# Producción dedicada: existe un único Caddy y PULSIA es su propietario.
# Se deshabilita la unidad estándar del paquete para evitar una segunda instancia.
if systemctl list-unit-files caddy.service >/dev/null 2>&1; then
  systemctl stop caddy.service >/dev/null 2>&1 || true
  systemctl disable caddy.service >/dev/null 2>&1 || true
fi

# Migración desde la versión anterior del instalador: elimina únicamente nuestro antiguo override de caddy.service.
OLD_CADDY_OVERRIDE="/etc/systemd/system/caddy.service.d/pulsia-inventario.conf"
if [[ -f "$OLD_CADDY_OVERRIDE" ]]; then
  warn "Se detectó la configuración Caddy de una versión anterior. Se migrará al servicio dedicado $CADDY_SERVICE_NAME."
  systemctl stop caddy >/dev/null 2>&1 || true
  rm -f "$OLD_CADDY_OVERRIDE"
  rmdir /etc/systemd/system/caddy.service.d >/dev/null 2>&1 || true
  systemctl daemon-reload
fi

port_conflict(){
  local port="$1"
  ss -ltnp 2>/dev/null | awk -v p=":$port" '$4 ~ p"$" {print}'
}

if CONFLICT_8080="$(port_conflict "$BACKEND_PORT")" && [[ -n "$CONFLICT_8080" ]]; then
  fail "TCP/$BACKEND_PORT ya está ocupado por otro proceso:\n$CONFLICT_8080\nLibere el puerto o revise el servicio existente."
fi
if CONFLICT_443="$(port_conflict "$HTTPS_PORT")" && [[ -n "$CONFLICT_443" ]]; then
  fail "TCP/$HTTPS_PORT sigue ocupado tras sanear procesos Caddy:\n$CONFLICT_443\nEl proceso restante no se identifica como Caddy; no se elimina automáticamente."
fi
if CONFLICT_ADMIN="$(port_conflict "$CADDY_ADMIN_PORT")" && [[ -n "$CONFLICT_ADMIN" ]]; then
  fail "TCP/$CADDY_ADMIN_PORT (API administrativa local de Caddy PULSIA) ya está ocupado por otro proceso:\n$CONFLICT_ADMIN"
fi

cat > "$SYSTEMD_FILE" <<EOF2
[Unit]
Description=PULSIA Inventario Tecnico (Django/Waitress)
After=network.target

[Service]
Type=simple
User=$RUN_USER
Group=$RUN_GROUP
WorkingDirectory=$PROJECT_ROOT
EnvironmentFile=$ENV_FILE
ExecStart=$VENV_DIR/bin/python -m waitress --listen=$BACKEND_HOST:$BACKEND_PORT config.wsgi:application
Restart=on-failure
RestartSec=3
PrivateTmp=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF2

cat > "$CADDYFILE" <<EOF2
{
    admin $CADDY_ADMIN_ADDR
    skip_install_trust
}

# HTTP queda únicamente como puerta de redirección. La aplicación se sirve siempre por HTTPS.
:$HTTP_PORT {
    redir https://{host}{uri} permanent
}

https://almacen, https://pizarra, https://localhost, https://127.0.0.1, https://${NETWORK_IP:-127.0.0.1} {
    tls internal
    # Django/Waitress escucha por HTTP solo en loopback. Informamos explícitamente
    # del esquema HTTPS original para que request.is_secure() sea correcto y
    # SECURE_SSL_REDIRECT no pueda crear un bucle detrás del proxy.
    reverse_proxy $BACKEND_HOST:$BACKEND_PORT {
        header_up X-Forwarded-Proto https
        header_up Host {host}
    }
    encode zstd gzip
    header {
        X-Content-Type-Options nosniff
        X-Frame-Options DENY
        Referrer-Policy same-origin
        Strict-Transport-Security "max-age=3600"
    }
}
EOF2
chmod 644 "$CADDYFILE"
caddy validate --config "$CADDYFILE" --adapter caddyfile

# Servicio Caddy dedicado: no sobrescribe /etc/caddy/Caddyfile ni la configuración de otros sitios.
CADDY_USER="caddy"
id "$CADDY_USER" >/dev/null 2>&1 || useradd --system --home "$CADDY_DATA_DIR" --shell /usr/sbin/nologin "$CADDY_USER"
CADDY_GROUP="$(id -gn "$CADDY_USER")"
chown -R "$CADDY_USER:$CADDY_GROUP" "$CADDY_DATA_DIR"
cat > "$CADDY_SYSTEMD_FILE" <<EOF2
[Unit]
Description=PULSIA Inventario HTTPS (Caddy dedicado)
After=network-online.target $SERVICE_NAME.service
Wants=network-online.target
Requires=$SERVICE_NAME.service

[Service]
Type=notify
User=$CADDY_USER
Group=$CADDY_GROUP
Environment=XDG_DATA_HOME=$CADDY_DATA_DIR
Environment=XDG_CONFIG_HOME=$CADDY_DATA_DIR
ExecStart=$(command -v caddy) run --environ --config $CADDYFILE --adapter caddyfile
ExecReload=$(command -v caddy) reload --config $CADDYFILE --adapter caddyfile --force
TimeoutStopSec=5s
LimitNOFILE=1048576
PrivateTmp=true
NoNewPrivileges=true
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF2

systemctl daemon-reload
systemctl enable "$SERVICE_NAME" "$CADDY_SERVICE_NAME" >/dev/null
systemctl restart "$SERVICE_NAME"
sleep 1
systemctl restart "$CADDY_SERVICE_NAME"

# Si falla un servicio, mostrar su journal inmediatamente.
if ! systemctl is-active --quiet "$SERVICE_NAME"; then
  journalctl -u "$SERVICE_NAME" -n 60 --no-pager || true
  fail "El servicio Django/Waitress no pudo arrancar."
fi
if ! systemctl is-active --quiet "$CADDY_SERVICE_NAME"; then
  journalctl -u "$CADDY_SERVICE_NAME" -n 60 --no-pager || true
  fail "El servicio HTTPS/Caddy no pudo arrancar."
fi
# Health check real del camino navegador -> HTTPS/Caddy -> Waitress/Django.
# -L sigue redirecciones y --max-redirs limita la cadena: un bucle HTTPS falla.
# Se usa -k únicamente aquí porque la CA todavía se exporta/instala más abajo.
HEALTH_URL="https://${NETWORK_IP:-127.0.0.1}/cuenta/login/"
if ! curl -kfsSL --max-redirs 5 --max-time 15 "$HEALTH_URL" -o /dev/null; then
  journalctl -u "$SERVICE_NAME" -n 80 --no-pager || true
  journalctl -u "$CADDY_SERVICE_NAME" -n 80 --no-pager || true
  fail "Health check HTTPS falló o detectó una cadena/bucle de redirecciones en $HEALTH_URL."
fi
HEALTH_CODE="$(curl -ksS --max-redirs 0 --max-time 10 -o /dev/null -w '%{http_code}' "$HEALTH_URL" || true)"
if [[ "$HEALTH_CODE" != "200" ]]; then
  fail "El login HTTPS no devuelve HTTP 200 (recibido: ${HEALTH_CODE:-sin respuesta}). Posible problema de proxy/redirect."
fi
ok "Health check HTTPS completo: login HTTP 200 y sin bucle de redirecciones."

# Resolver 'almacen' en el propio servidor sin cambiar hostname ni depender de DNS externo.
LAN_IP="$(ip -o -4 addr show scope global 2>/dev/null | awk '{split($4,a,"/"); print a[1]; exit}')"
if [[ -n "$LAN_IP" ]]; then
  sed -i '/# PULSIA Inventario$/d' /etc/hosts || true
  printf '%s almacen pizarra # PULSIA Inventario\n' "$LAN_IP" >> /etc/hosts
  ok "Resolución local añadida: almacen y pizarra -> $LAN_IP"
fi

# Firewall: HTTPS/443 sirve la aplicación; HTTP/80 solo redirige a HTTPS. Nunca se expone 8080.
LOCAL_CIDR="$(ip -o -4 addr show scope global 2>/dev/null | awk '{print $4; exit}')"
LAN_CIDR=""
if [[ -n "$LOCAL_CIDR" ]]; then
  LAN_CIDR="$($VENV_DIR/bin/python - "$LOCAL_CIDR" <<'PY'
import ipaddress, sys
print(ipaddress.ip_interface(sys.argv[1]).network)
PY
)"
fi
if command -v ufw >/dev/null 2>&1 && [[ -n "$LAN_CIDR" ]]; then
  ufw allow from "$LAN_CIDR" to any port 80 proto tcp comment 'PULSIA Inventario HTTP redirect' >/dev/null || true
  ufw allow from "$LAN_CIDR" to any port 443 proto tcp comment 'PULSIA Inventario HTTPS' >/dev/null || true
  ok "UFW: TCP/443 permitido para HTTPS y TCP/80 únicamente para redirección desde $LAN_CIDR."
elif command -v firewall-cmd >/dev/null 2>&1 && [[ -n "$LAN_CIDR" ]] && systemctl is-active --quiet firewalld; then
  firewall-cmd --permanent --add-rich-rule="rule family=ipv4 source address=$LAN_CIDR port port=80 protocol=tcp accept" >/dev/null
  firewall-cmd --permanent --add-rich-rule="rule family=ipv4 source address=$LAN_CIDR port port=443 protocol=tcp accept" >/dev/null
  firewall-cmd --reload >/dev/null
  ok "firewalld: TCP/443 permitido para HTTPS y TCP/80 únicamente para redirección desde $LAN_CIDR."
elif command -v nft >/dev/null 2>&1; then
  warn "nftables detectado sin UFW/firewalld. No se alteran automáticamente políticas nftables corporativas. Permita TCP/443 desde la LAN si fuera necesario."
elif [[ -z "$LAN_CIDR" ]]; then
  warn "No se pudo determinar de forma segura la subred LAN. No se crea una regla amplia automáticamente."
fi

# ESET/seguridad corporativa: detectar y diagnosticar, nunca desactivar ni eludir.
if pgrep -afi 'eset|eea|efs' >/dev/null 2>&1 || [[ -d /opt/eset ]]; then
  warn "ESET detectado. El instalador no desactiva ni elude sus políticas."
  warn "Si la LAN no accede por IP, autorice TCP/80 entrante para $(command -v caddy) desde ${LAN_CIDR:-la LAN privada}."
fi

# Obtener y publicar la CA de ESTA instancia PULSIA. Los clientes HTTPS pueden descargar esta CA desde la propia aplicación y confiarla explícitamente.
sleep 2
CADDY_ROOT_CERT="$(find "$CADDY_DATA_DIR" -type f -path '*/caddy/pki/authorities/local/root.crt' -print -quit 2>/dev/null || true)"
if [[ -z "$CADDY_ROOT_CERT" ]]; then
  CADDY_ROOT_CERT="$(find "$CADDY_DATA_DIR" -type f -path '*/pki/authorities/local/root.crt' -print -quit 2>/dev/null || true)"
fi
if [[ -z "$CADDY_ROOT_CERT" ]]; then
  journalctl -u "$CADDY_SERVICE_NAME" -n 60 --no-pager || true
  fail "Caddy está activo pero no se encontró la CA raíz de la instancia PULSIA en $CADDY_DATA_DIR."
fi

SYSTEM_CA="/usr/local/share/ca-certificates/PULSIA-Inventario-Root-CA.crt"
cp -f "$CADDY_ROOT_CERT" "$SYSTEM_CA"
chmod 644 "$SYSTEM_CA"
update-ca-certificates >/dev/null

cp -f "$CADDY_ROOT_CERT" "$CERT_DIR/PULSIA-Inventario-Root-CA.crt"
chown "$RUN_USER:$RUN_GROUP" "$CERT_DIR/PULSIA-Inventario-Root-CA.crt" || true
chmod 644 "$CERT_DIR/PULSIA-Inventario-Root-CA.crt"
ok "CA PULSIA instalada localmente para la compatibilidad HTTPS del servidor."

# Chrome/Chromium en Linux puede usar NSS. Instalar la misma CA para el usuario que lanzó sudo.
apt_install libnss3-tools
install_nss_ca_for_user(){
  local usr="$1" home nssdb profile
  [[ -n "$usr" && "$usr" != root ]] || return 0
  home="$(getent passwd "$usr" | cut -d: -f6)"
  [[ -n "$home" && -d "$home" ]] || return 0
  nssdb="$home/.pki/nssdb"
  install -d -m 700 -o "$usr" -g "$(id -gn "$usr")" "$nssdb"
  if [[ ! -f "$nssdb/cert9.db" ]]; then
    sudo -u "$usr" certutil -N -d "sql:$nssdb" --empty-password >/dev/null 2>&1 || true
  fi
  sudo -u "$usr" certutil -D -d "sql:$nssdb" -n "PULSIA Inventario Root CA" >/dev/null 2>&1 || true
  sudo -u "$usr" certutil -A -d "sql:$nssdb" -n "PULSIA Inventario Root CA" -t "C,," -i "$CADDY_ROOT_CERT" >/dev/null 2>&1 || true
  if [[ -d "$home/.mozilla/firefox" ]]; then
    while IFS= read -r profile; do
      sudo -u "$usr" certutil -D -d "sql:$profile" -n "PULSIA Inventario Root CA" >/dev/null 2>&1 || true
      sudo -u "$usr" certutil -A -d "sql:$profile" -n "PULSIA Inventario Root CA" -t "C,," -i "$CADDY_ROOT_CERT" >/dev/null 2>&1 || true
    done < <(find "$home/.mozilla/firefox" -mindepth 1 -maxdepth 1 -type d -exec test -f '{}/cert9.db' ';' -print 2>/dev/null)
  fi
}
install_nss_ca_for_user "${SUDO_USER:-}"

# Verificación criptográfica estricta: cada identidad HTTPS debe validar contra la CA publicada.
for HTTPS_TARGET in "almacen" "pizarra" "127.0.0.1" "${NETWORK_IP:-127.0.0.1}"; do
  if curl --cacert "$CADDY_ROOT_CERT" -fsS "https://$HTTPS_TARGET/" -o /dev/null; then
    ok "Certificado HTTPS válido para $HTTPS_TARGET contra la CA PULSIA."
  else
    fail "El certificado HTTPS de $HTTPS_TARGET no valida contra la CA generada por PULSIA."
  fi
done

# Pruebas por capas.
if curl -fsS -H "Host: almacen" -H "X-Forwarded-Proto: https" "http://$BACKEND_HOST:$BACKEND_PORT/" -o /dev/null; then
  ok "Backend responde en $BACKEND_HOST:$BACKEND_PORT (solo localhost)."
else
  journalctl -u "$SERVICE_NAME" -n 40 --no-pager || true
  fail "Backend no responde en $BACKEND_HOST:$BACKEND_PORT."
fi

if ss -ltn | grep -Eq '[:.]443[[:space:]]'; then
  ok "Caddy escucha en TCP/443."
else
  journalctl -u "$CADDY_SERVICE_NAME" -n 40 --no-pager || true
  fail "No se detecta escucha TCP/443."
fi

if [[ -n "${LAN_IP:-}" ]] && curl --cacert "$CADDY_ROOT_CERT" -fsS "https://$LAN_IP/" -o /dev/null; then
  ok "Acceso web LAN HTTPS responde en https://$LAN_IP"
else
  fail "HTTPS por IP LAN no respondió o no validó el certificado."
fi
HTTP_CODE="$(curl -sS -o /dev/null -w '%{http_code}' "http://${LAN_IP:-127.0.0.1}/" || true)"
if [[ "$HTTP_CODE" =~ ^30[12378]$ ]]; then
  ok "HTTP redirige a HTTPS (código $HTTP_CODE)."
else
  warn "La redirección HTTP->HTTPS devolvió código ${HTTP_CODE:-desconocido}."
fi

mkdir -p "$SYSTEM_CONFIG_DIR"
python3 - "$MANIFEST_FILE" "$MACHINE_ID" "$PROJECT_ROOT" <<'PYMAN'
import json,sys,os,datetime
p,machine,root=sys.argv[1:]
data={"schema":1,"installed_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"machine_id":machine,"project_root":root,"service":"pulsia-inventario","caddy_service":"pulsia-inventario-caddy"}
t=p+".tmp"
with open(t,"w",encoding="utf-8") as f: json.dump(data,f,ensure_ascii=False,indent=2)
os.replace(t,p)
PYMAN
chmod 600 "$MANIFEST_FILE" || true
ok "Manifiesto de instalación actualizado de forma atómica."
INSTALL_COMMITTED=1
rm -rf "$VENV_PREVIOUS"
phase "07 Resultado del servicio"
info "Instalación/actualización terminada."
info "Python usado       : $PYTHON_BIN ($PYTHON_VERSION)"
info "Virtualización    : $VIRT_TYPE"
info "Backend privado   : http://$BACKEND_HOST:$BACKEND_PORT"
if [[ -n "$LAN_IP" ]]; then
  info "ACCESO CLIENTES    : https://$LAN_IP"
  info "IP del servidor    : $LAN_IP"
else
  warn "No se pudo determinar la IP LAN para mostrar la URL de acceso."
fi
info "Nombres HTTPS      : https://almacen y https://pizarra"
info "No se ha abierto TCP/$BACKEND_PORT en el firewall."
if (( APT_FALLBACK == 1 )); then
  warn "APT tuvo repositorios de terceros con errores. La instalación continuó sin modificarlos; conviene corregirlos posteriormente."
fi
if [[ -f "$CERT_DIR/PULSIA-Inventario-Root-CA.crt" ]]; then
  info "CA local HTTPS     : $CERT_DIR/PULSIA-Inventario-Root-CA.crt"
fi

info "Instalación del SERVICIO completada. No se han creado usuarios ni compilado clientes."
info "Siguiente paso opcional: sudo ./06_crear_primer_usuario.sh"
info "Localizador: ./localizador.sh (genera conexion.sh con la IP actual del servidor)"
