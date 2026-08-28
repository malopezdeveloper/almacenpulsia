#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/pulsia_common.sh"
require_root
[[ -r /etc/os-release ]] || fail "No se puede identificar la distribución Linux."
. /etc/os-release
case "${ID:-}" in ubuntu|debian) ;; *) fail "Build automático soportado en Debian/Ubuntu." ;; esac

BOOTSTRAP_PYTHON_VERSION="${PULSIA_PYTHON_VERSION:-3.12.10}"
CLIENT_BUILD_PYTHON_VERSION="${PULSIA_CLIENT_BUILD_PYTHON_VERSION:-$BOOTSTRAP_PYTHON_VERSION}"
CLIENT_OPENSSL_VERSION="${PULSIA_CLIENT_OPENSSL_VERSION:-3.5.7}"
WINE_SOURCE_FALLBACK_VERSION="${PULSIA_WINE_SOURCE_FALLBACK_VERSION:-11.14}"
PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
SYSTEM_CONFIG_DIR="/etc/pulsia-inventario"
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

ensure_client_build_python(){
  local found ver mm prefix bin build_dir tarball
  found="$(find_client_build_python || true)"
  if [[ -n "$found" ]]; then
    CLIENT_BUILD_PYTHON="$found"
    ok "Python de compilación cliente Linux: $CLIENT_BUILD_PYTHON (libpython compartida disponible)."
    return 0
  fi

  ver="$CLIENT_BUILD_PYTHON_VERSION"
  mm="${ver%.*}"
  prefix="/opt/pulsia/build-python-$ver"
  bin="$prefix/bin/python$mm"
  build_dir="/tmp/pulsia-client-build-python-$ver"
  tarball="/tmp/Python-client-build-$ver.tgz"

  if [[ -x "$bin" ]] && python_has_shared_library "$bin"; then
    CLIENT_BUILD_PYTHON="$bin"
    ok "Python dedicado de compilación reutilizado: $CLIENT_BUILD_PYTHON"
    return 0
  fi

  warn "No hay Python >= 3.10 con libpython compartida apto para PyInstaller."
  info "Se construirá Python $ver SOLO para compilar el cliente Linux en $prefix."
  info "El Python del servidor ($PYTHON_BIN) no se modifica."

  apt_install \
    build-essential ca-certificates curl xz-utils \
    libssl-dev zlib1g-dev libncurses-dev \
    libreadline-dev libsqlite3-dev libgdbm-dev libdb-dev \
    libbz2-dev libexpat1-dev liblzma-dev tk-dev libffi-dev uuid-dev

  rm -rf "$prefix" "$build_dir" "$tarball"
  mkdir -p "$build_dir" "$(dirname "$prefix")"

  curl -fL --retry 5 --retry-delay 3 --connect-timeout 15 \
    "https://www.python.org/ftp/python/$ver/Python-$ver.tgz" -o "$tarball"
  tar -xzf "$tarball" -C "$build_dir" --strip-components=1

  pushd "$build_dir" >/dev/null
  LDFLAGS="-Wl,-rpath,$prefix/lib" \
    ./configure \
      --prefix="$prefix" \
      --with-ensurepip=install \
      --enable-shared
  make -j"$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)"
  make altinstall
  popd >/dev/null
  rm -rf "$build_dir" "$tarball"

  [[ -x "$bin" ]] || fail "No se encontró el Python de compilación esperado: $bin"
  python_has_shared_library "$bin" || \
    fail "Python de compilación creado, pero libpython compartida no está disponible."

  CLIENT_BUILD_PYTHON="$bin"
  ok "Python de compilación cliente preparado: $CLIENT_BUILD_PYTHON"
  "$CLIENT_BUILD_PYTHON" - <<'PY'
import os, sys, sysconfig
print("[OK] Python build:", sys.version.split()[0])
print("[OK] Py_ENABLE_SHARED:", sysconfig.get_config_var("Py_ENABLE_SHARED"))
print("[OK] libpython:", os.path.join(
    sysconfig.get_config_var("LIBDIR") or "",
    sysconfig.get_config_var("LDLIBRARY") or ""
))
PY
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


apt_package_exists(){
  local p="$1"
  apt-cache show "$p" >/dev/null 2>&1
}

apt_install_available(){
  local p available=()
  for p in "$@"; do
    apt_package_exists "$p" && available+=("$p")
  done
  ((${#available[@]} > 0)) || return 0
  apt_install "${available[@]}"
}

ensure_build_locale(){
  # Wine/Qt generan avisos o comportamientos inconsistentes con C/POSIX en
  # instalaciones mínimas. Se instala/configura un locale UTF-8 automáticamente.
  apt_install_available locales
  if locale -a 2>/dev/null | grep -Eqi '^en_US\.utf-?8$'; then
    export LANG=en_US.UTF-8
    export LC_ALL=en_US.UTF-8
    return 0
  fi

  if command -v locale-gen >/dev/null 2>&1; then
    info "Configurando locale UTF-8 para el entorno de compilación..."
    grep -Eq '^[# ]*en_US.UTF-8 UTF-8' /etc/locale.gen 2>/dev/null && \
      sed -i 's/^[# ]*en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen || \
      printf 'en_US.UTF-8 UTF-8\n' >> /etc/locale.gen
    locale-gen en_US.UTF-8 >/dev/null
  fi

  if locale -a 2>/dev/null | grep -Eqi '^en_US\.utf-?8$'; then
    export LANG=en_US.UTF-8
    export LC_ALL=en_US.UTF-8
    ok "Locale en_US.UTF-8 preparado."
  else
    warn "No se pudo generar en_US.UTF-8; se continuará con C.UTF-8."
    export LANG=C.UTF-8
    export LC_ALL=C.UTF-8
  fi
}

ensure_windows_build_system(){
  # Se instala/configura TODO lo que utiliza el build. apt es idempotente:
  # si ya existe, lo valida; si falta, lo instala.
  apt_install_available \
    ca-certificates curl xz-utils file zip unzip coreutils procps grep sed gawk cabextract \
    xvfb xauth dbus-x11 \
    build-essential gcc g++ make flex bison pkg-config gcc-mingw-w64-x86-64 \
    libx11-dev libxext-dev libxrender-dev libxrandr-dev libxcursor-dev \
    libxi-dev libxinerama-dev libxcomposite-dev libxfixes-dev \
    libfreetype6-dev libfreetype-dev libfontconfig1-dev libxkbcommon-dev \
    libgnutls28-dev libdbus-1-dev libudev-dev libunwind-dev \
    libasound2-dev libpulse-dev \
    mesa-utils libgl1 libegl1

  ensure_build_locale

  for c in curl xvfb-run timeout file zip; do
    command -v "$c" >/dev/null 2>&1 || fail "La dependencia '$c' se solicitó al sistema pero no quedó operativa."
  done
  ok "Entorno Linux de compilación Windows preparado y validado."
}

ensure_distro_wine_packages(){
  local packages=() p
  local foreign_arches
  apt_update_safe

  # Componentes nativos x86_64.
  for p in wine wine64 libwine fonts-wine wine64-tools wine-binfmt; do
    apt_package_exists "$p" && packages+=("$p")
  done

  # El instalador oficial Python amd64 utiliza un bootstrap PE32/MSI. Si la
  # distribución tiene i386 habilitado, se aseguran también los componentes
  # WoW64/32-bit disponibles. No se fuerza un nombre inexistente.
  foreign_arches="$(dpkg --print-foreign-architectures 2>/dev/null || true)"
  if grep -Fxq i386 <<<"$foreign_arches"; then
    for p in wine32:i386 libwine:i386 libc6:i386; do
      apt_package_exists "$p" && packages+=("$p")
    done
  else
    warn "Arquitectura i386 no está habilitada. Wine distro puede usar WoW64 experimental; se validará con el instalador real."
  fi

  if ((${#packages[@]} == 0)); then
    warn "La distribución no publica paquetes Wine utilizables en los repositorios activos."
    return 1
  fi

  # Evita duplicados conservando orden.
  mapfile -t packages < <(printf '%s\n' "${packages[@]}" | awk '!seen[$0]++')

  info "Instalando/asegurando runtime Wine de la distribución: ${packages[*]}"
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${packages[@]}" || return 1

  # Diagnóstico explícito de arquitectura: no se presupone que wine32 exista.
  info "Arquitecturas dpkg: nativa=$(dpkg --print-architecture 2>/dev/null || echo desconocida), adicionales=$(dpkg --print-foreign-architectures 2>/dev/null | tr '\n' ',' | sed 's/,$//' || true)"

  if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files systemd-binfmt.service >/dev/null 2>&1; then
    systemctl restart systemd-binfmt.service >/dev/null 2>&1 || true
  fi

  hash -r
  return 0
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


wine_candidate_version(){
  local candidate="$1" out
  out="$("$candidate" --version 2>/dev/null || true)"
  wine_version_number "$out"
}

probe_wine_candidate(){
  local candidate="$1" seconds="${PULSIA_WINE_PROBE_TIMEOUT:-45}"
  local tmp rc
  tmp="$(mktemp -d /tmp/pulsia-wine-probe-XXXXXX)"
  mkdir -p "$tmp/prefix"
  info "Probando capacidad real de Wine: $candidate" >&2

  set +e
  WINEPREFIX="$tmp/prefix" WINEARCH=win64 WINEDEBUG=-all \
    timeout --signal=TERM --kill-after=10s "${seconds}s" \
    xvfb-run -a "$candidate" cmd /c exit >/dev/null 2>&1
  rc=$?
  set -e

  # El prefijo de prueba es desechable. El grupo creado por timeout limita
  # procesos bloqueados aunque el paquete no exponga wineserver.
  rm -rf "$tmp" >/dev/null 2>&1 || true

  if [[ $rc -eq 0 ]]; then
    return 0
  fi
  warn "Wine descartado por prueba funcional (rc=$rc): $candidate" >&2
  return 1
}

wine_candidates(){
  local candidate pkg
  declare -A seen=()

  emit(){
    local c="$1"
    [[ -n "$c" ]] || return 0
    c="$(readlink -f "$c" 2>/dev/null || printf '%s' "$c")"
    [[ -x "$c" ]] || return 0
    [[ -n "${seen[$c]:-}" ]] && return 0
    seen[$c]=1
    printf '%s\n' "$c"
  }

  emit "$(command -v wine 2>/dev/null || true)"
  emit "$(command -v wine64 2>/dev/null || true)"

  # Inventario de paquetes instalados: compatible con Debian/Ubuntu/WineHQ y
  # layouts donde /usr/bin/wine es solo un wrapper.
  if command -v dpkg-query >/dev/null 2>&1; then
    while IFS= read -r pkg; do
      [[ -n "$pkg" ]] || continue
      while IFS= read -r candidate; do
        case "$(basename "$candidate")" in
          wine|wine64) emit "$candidate" ;;
        esac
      done < <(dpkg -L "$pkg" 2>/dev/null || true)
    done < <(dpkg-query -W -f='${binary:Package}\n' 'wine*' 'libwine*' 2>/dev/null | sort -u || true)
  fi

  for candidate in \
      /usr/bin/wine /usr/bin/wine64 \
      /usr/lib/wine/wine /usr/lib/wine/wine64 \
      /usr/lib64/wine/wine /usr/lib64/wine/wine64 \
      /usr/lib/x86_64-linux-gnu/wine/wine \
      /usr/lib/x86_64-linux-gnu/wine/wine64; do
    emit "$candidate"
  done

  # Wines privados PULSIA ya construidos también son candidatos; no se asume
  # que el marcador de una versión concreta siga vigente.
  for candidate in /opt/pulsia/wine-private-*/bin/wine; do
    [[ -e "$candidate" ]] && emit "$candidate"
  done
}

find_usable_wine(){
  local candidate current
  while IFS= read -r candidate; do
    [[ -n "$candidate" ]] || continue
    current="$(wine_candidate_version "$candidate")"
    if [[ -z "$current" ]]; then
      warn "Wine sin versión detectable, descartado: $candidate" >&2
      continue
    fi
    if ! version_ge "$current" "8.18"; then
      warn "Wine $current demasiado antiguo, descartado: $candidate" >&2
      continue
    fi
    if probe_wine_candidate "$candidate"; then
      printf '%s|%s\n' "$candidate" "$current"
      return 0
    fi
  done < <(wine_candidates)
  return 1
}


find_version_compatible_wine(){
  local candidate current
  while IFS= read -r candidate; do
    [[ -n "$candidate" ]] || continue
    current="$(wine_candidate_version "$candidate")"
    [[ -n "$current" ]] || continue
    if version_ge "$current" "8.18"; then
      printf '%s|%s\n' "$candidate" "$current"
      return 0
    fi
  done < <(wine_candidates)
  return 1
}


find_distro_version_compatible_wine(){
  local candidate current
  while IFS= read -r candidate; do
    [[ -n "$candidate" ]] || continue
    # El Wine privado actual de PULSIA se compila --enable-win64 y NO aporta
    # un WoW64 completo. El instalador oficial de Python amd64 arranca mediante
    # un bootstrap PE32/MSI y necesita syswow64/ntdll de 32 bits.
    [[ "$candidate" == /opt/pulsia/wine-private-* ]] && continue

    current="$(wine_candidate_version "$candidate")"
    [[ -n "$current" ]] || continue
    if version_ge "$current" "8.18"; then
      printf '%s|%s\n' "$candidate" "$current"
      return 0
    fi
  done < <(wine_candidates)
  return 1
}

ensure_wine_for_windows_build(){
  local selected candidate current

  ensure_windows_build_system

  # Este flujo necesita ejecutar el bootstrap PE32/MSI del instalador oficial
  # Python Windows amd64. Por ello se exige Wine de la distribución con soporte
  # WoW64/i386 instalado. El Wine privado PULSIA --enable-win64 NO es un fallback
  # válido para este build y no se selecciona nunca aquí.
  if ! ensure_distro_wine_packages; then
    fail "No se pudo preparar Wine de la distribución requerido para el build Windows."
  fi

  selected="$(find_distro_version_compatible_wine || true)"
  if [[ -z "$selected" ]]; then
    fail "No existe Wine de la distribución >= 8.18 apto para el build Windows. No se usará el Wine privado win64-only."
  fi

  candidate="${selected%%|*}"
  current="${selected#*|}"
  SELECTED_WINE_BIN="$candidate"
  SELECTED_WINE_KIND="distro-provisioned"

  ok "Wine de distribución seleccionado: $SELECTED_WINE_BIN (Wine $current)."
  info "Se mantiene este mismo runtime durante preflight, instalación Python, pip y PyInstaller."
  info "El Wine privado PULSIA queda excluido de este flujo porque no aporta WoW64 completo."
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


build_owner(){
  local owner
  owner="$(stat -c '%U' "$PROJECT_ROOT/data" 2>/dev/null || true)"
  [[ -n "$owner" && "$owner" != UNKNOWN ]] || owner="$(run_user)"
  id "$owner" >/dev/null 2>&1 || owner=root
  printf '%s\n' "$owner"
}

require_client_metadata(){
  [[ -f "$CLIENT_APP_DIR/servidor_cliente.ini" ]] ||     fail "Falta servidor_cliente.ini. Instale primero el servicio con 01_instalar_servicio.sh."
  local cert="$CLIENT_APP_DIR/certificados/PULSIA-Inventario-Root-CA.crt"
  [[ -f "$cert" ]] || fail "Falta la CA del servidor en la carpeta cliente. Ejecute 01_instalar_servicio.sh."
}

