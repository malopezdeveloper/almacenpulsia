#!/usr/bin/env bash
set -Eeuo pipefail

APP_SERVICE="pulsia-inventario"
CADDY_SERVICE="pulsia-inventario-caddy"
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
SYSTEM_CONFIG_DIR="/etc/pulsia-inventario"
CADDY_DATA_DIR="/var/lib/${CADDY_SERVICE}"
SYSTEM_CA="/usr/local/share/ca-certificates/PULSIA-Inventario-Root-CA.crt"
APP_CLIENT_OUTPUT_DIR="$PROJECT_ROOT/app cliente"
TEMP_LOG="/var/log/pulsia-inventario-desinstalacion.log"
RESTORE_NETWORK=0
PURGE_DATA=0
PURGE_ALL_CADDY=1
ASSUME_YES=0
DIAGNOSTIC_ONLY=0
MAX_PASSES=5

for arg in "$@"; do
  case "$arg" in
    --restaurar-red) RESTORE_NETWORK=1 ;;
    --purgar-datos) PURGE_DATA=1 ;;
    --conservar-caddy-global) PURGE_ALL_CADDY=0 ;;
    --si|--yes|-y) ASSUME_YES=1 ;;
    --diagnostico) DIAGNOSTIC_ONLY=1 ;;
  esac
done

ok(){ printf '\033[32m[OK]\033[0m %s\n' "$*"; }
info(){ printf '\033[36m[INFO]\033[0m %s\n' "$*"; }
warn(){ printf '\033[33m[AVISO]\033[0m %s\n' "$*"; }
fail(){ printf '\033[31m[ERROR]\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || fail "Ejecute: sudo bash \"$0\""
touch "$TEMP_LOG" 2>/dev/null || TEMP_LOG="/tmp/PULSIA-Inventario-desinstalacion-linux.log"
exec > >(tee -a "$TEMP_LOG") 2>&1

is_pulsia_waitress_pid(){
  local pid="$1" cmd
  [[ -r "/proc/$pid/cmdline" ]] || return 1
  cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
  [[ "$cmd" == *waitress* && ( "$cmd" == *"config.wsgi"* || "$cmd" == *"127.0.0.1:8080"* || "$cmd" == *"--listen=127.0.0.1:8080"* ) ]]
}

remove_host_alias(){
  local file="/etc/hosts" tmp
  [[ -f "$file" ]] || return 0
  tmp="$(mktemp)"
  awk '
  {
    raw=$0
    split(raw, c, "#")
    body=c[1]
    n=split(body, f, /[[:space:]]+/)
    # Re-tokenize ignoring leading blanks.
    delete t; m=0
    for(i=1;i<=n;i++) if(f[i] != "") t[++m]=f[i]
    if(m < 2){ print raw; next }
    ip=t[1]; out=""; kept=0
    for(i=2;i<=m;i++){
      if(tolower(t[i]) != "almacen"){
        out=out (kept?"\t":"") t[i]; kept++
      }
    }
    if(kept==m-1){ print raw; next }
    if(kept==0) next
    line=ip "\t" out
    if(index(raw,"#")>0){
      comment=substr(raw,index(raw,"#")+1); gsub(/^[[:space:]]+|[[:space:]]+$/, "", comment)
      if(comment!="") line=line "\t# " comment
    }
    print line
  }' "$file" > "$tmp"
  cat "$tmp" > "$file"
  rm -f "$tmp"
}

flush_dns(){
  if command -v resolvectl >/dev/null 2>&1; then resolvectl flush-caches >/dev/null 2>&1 || true; fi
  if command -v systemd-resolve >/dev/null 2>&1; then systemd-resolve --flush-caches >/dev/null 2>&1 || true; fi
  if command -v nscd >/dev/null 2>&1; then systemctl restart nscd >/dev/null 2>&1 || true; fi
  if command -v dnsmasq >/dev/null 2>&1 && systemctl is-active --quiet dnsmasq 2>/dev/null; then systemctl restart dnsmasq >/dev/null 2>&1 || true; fi
}

stop_and_remove_units(){
  local svc unit
  for svc in "$CADDY_SERVICE" "$APP_SERVICE"; do
    systemctl stop "$svc.service" >/dev/null 2>&1 || true
    systemctl disable "$svc.service" >/dev/null 2>&1 || true
    systemctl mask "$svc.service" >/dev/null 2>&1 || true
    rm -f "/etc/systemd/system/$svc.service" "/lib/systemd/system/$svc.service" "/usr/lib/systemd/system/$svc.service"
  done

  if (( PURGE_ALL_CADDY )); then
    systemctl stop caddy.service >/dev/null 2>&1 || true
    systemctl disable caddy.service >/dev/null 2>&1 || true
    systemctl mask caddy.service >/dev/null 2>&1 || true
    for unit in /etc/systemd/system/*caddy*.service /lib/systemd/system/*caddy*.service /usr/lib/systemd/system/*caddy*.service; do
      [[ -e "$unit" ]] || continue
      rm -f "$unit"
    done
  fi
  systemctl daemon-reload >/dev/null 2>&1 || true
  systemctl reset-failed >/dev/null 2>&1 || true
}

kill_residual_processes(){
  local pid cmd
  while IFS= read -r pid; do
    [[ -n "$pid" ]] || continue
    if (( PURGE_ALL_CADDY )); then
      cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
      warn "Finalizando Caddy residual PID $pid ${cmd:+| $cmd}"
      kill "$pid" >/dev/null 2>&1 || true
      sleep 0.3
      kill -9 "$pid" >/dev/null 2>&1 || true
    else
      cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
      if [[ "$cmd" == *"$SYSTEM_CONFIG_DIR"* || "$cmd" == *"$CADDY_DATA_DIR"* || "$cmd" == *"pulsia-inventario"* ]]; then
        kill "$pid" >/dev/null 2>&1 || true; sleep 0.3; kill -9 "$pid" >/dev/null 2>&1 || true
      fi
    fi
  done < <(pgrep -x caddy 2>/dev/null || true)

  for pid in /proc/[0-9]*; do
    pid="${pid##*/}"
    if is_pulsia_waitress_pid "$pid"; then
      cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
      warn "Finalizando Waitress PULSIA residual PID $pid | $cmd"
      kill "$pid" >/dev/null 2>&1 || true; sleep 0.3; kill -9 "$pid" >/dev/null 2>&1 || true
    fi
  done
}

purge_caddy_global(){
  (( PURGE_ALL_CADDY )) || return 0
  local pkgs
  pkgs="$(dpkg-query -W -f='${binary:Package}\n' 2>/dev/null | awk '/^caddy([:$-]|$)/ {print}' | sort -u || true)"
  if [[ -n "$pkgs" ]]; then
    info "Purgando paquetes Caddy: $pkgs"
    DEBIAN_FRONTEND=noninteractive apt-get purge -y $pkgs >/dev/null 2>&1 || true
    DEBIAN_FRONTEND=noninteractive apt-get autoremove -y >/dev/null 2>&1 || true
  fi

  rm -f /etc/apt/sources.list.d/*caddy* /etc/apt/keyrings/*caddy* /usr/share/keyrings/*caddy* 2>/dev/null || true
  rm -rf /etc/caddy /var/lib/caddy /var/log/caddy /usr/share/caddy 2>/dev/null || true
  # Si quedó un binario manual fuera del gestor de paquetes, retirarlo también.
  for f in /usr/bin/caddy /usr/local/bin/caddy /opt/caddy/caddy; do
    [[ -e "$f" ]] && rm -f "$f"
  done

  for home in /root /home/*; do
    [[ -d "$home" ]] || continue
    rm -rf "$home/.local/share/caddy" "$home/.config/caddy" "$home/.cache/caddy" 2>/dev/null || true
  done
}

purge_pulsia_winehq(){
  local marker="$SYSTEM_CONFIG_DIR/winehq-installed-by-pulsia"
  local pkg_file="$SYSTEM_CONFIG_DIR/winehq-packages-by-pulsia"
  local sources key packages=()

  [[ -f "$marker" ]] || return 0
  info "WineHQ fue instalado por PULSIA; retirando esa dependencia y su repositorio."

  sources="$(sed -n 's/^sources=//p' "$marker" | head -n1)"
  key="$(sed -n 's/^key=//p' "$marker" | head -n1)"

  if [[ -f "$pkg_file" ]]; then
    while IFS= read -r p; do
      [[ -n "$p" ]] && packages+=("$p")
    done < "$pkg_file"
  fi

  if ((${#packages[@]})); then
    DEBIAN_FRONTEND=noninteractive apt-get purge -y "${packages[@]}" >/dev/null 2>&1 || true
  fi

  [[ -n "$sources" ]] && rm -f "$sources" 2>/dev/null || true
  [[ -n "$key" ]] && rm -f "$key" 2>/dev/null || true

  # Solo elimina restos WineHQ inequívocamente creados/registrados por PULSIA.
  # Los prefijos Wine personales (~/.wine) no se tocan.
  rm -f /etc/apt/sources.list.d/winehq-*.sources 2>/dev/null || true
  rm -f /etc/apt/keyrings/winehq-archive.key 2>/dev/null || true
}

remove_pulsia_files(){
  rm -rf "$SYSTEM_CONFIG_DIR" "$CADDY_DATA_DIR"
  rm -f "$SYSTEM_CA"

  # Python dedicado usado exclusivamente para compilar el cliente Linux.
  # No se elimina el Python del sistema ni el runtime privado del servidor aquí.
  rm -rf /opt/pulsia/build-python-* 2>/dev/null || true
  rm -rf /opt/pulsia/client-openssl-* 2>/dev/null || true
  rm -rf /opt/pulsia/wine-private-* 2>/dev/null || true
  rm -rf "$PROJECT_ROOT/cliente/PULSIA_Inventario_Cliente/.build-wine-windows" 2>/dev/null || true

  # CAs/configuración generadas dentro del proyecto y del cliente portable.
  rm -f "$PROJECT_ROOT/certs/PULSIA-Inventario-Root-CA.crt" 2>/dev/null || true
  rm -f "$PROJECT_ROOT/cliente/PULSIA-Inventario-Root-CA.crt" 2>/dev/null || true
  rm -f "$PROJECT_ROOT/cliente/servidor_cliente.ini" 2>/dev/null || true
  rm -f "$PROJECT_ROOT/cliente/PULSIA_Inventario_Cliente/servidor_cliente.ini" 2>/dev/null || true
  rm -f "$PROJECT_ROOT/cliente/PULSIA_Inventario_Cliente/certificados/PULSIA-Inventario-Root-CA.crt" 2>/dev/null || true
  rm -rf "$APP_CLIENT_OUTPUT_DIR" 2>/dev/null || true
  rm -f "$PROJECT_ROOT/cliente/PULSIA_App_Cliente_Windows.zip" "$PROJECT_ROOT/cliente/PULSIA_App_Cliente_Linux.tar.gz" 2>/dev/null || true
  rm -f "$PROJECT_ROOT/cliente/PULSIA_Inventario_Cliente_USB.zip" "$PROJECT_ROOT/cliente/PULSIA_Cliente_Windows.zip" "$PROJECT_ROOT/cliente/PULSIA_Cliente_Linux.tar.gz" 2>/dev/null || true

  # Trust store: refrescar después de eliminar la CA fuente.
  update-ca-certificates --fresh >/dev/null 2>&1 || update-ca-certificates >/dev/null 2>&1 || true
  find /etc/ssl/certs -maxdepth 1 -type l -iname '*pulsia*' -delete 2>/dev/null || true

  # Certificados NSS que pudo instalar PULSIA.
  if command -v certutil >/dev/null 2>&1; then
    local home profile
    for home in /root /home/*; do
      [[ -d "$home" ]] || continue
      if [[ -d "$home/.pki/nssdb" ]]; then certutil -D -d "sql:$home/.pki/nssdb" -n "PULSIA Inventario Root CA" >/dev/null 2>&1 || true; fi
      if [[ -d "$home/.mozilla/firefox" ]]; then
        while IFS= read -r profile; do certutil -D -d "sql:$profile" -n "PULSIA Inventario Root CA" >/dev/null 2>&1 || true; done < <(find "$home/.mozilla/firefox" -mindepth 1 -maxdepth 1 -type d -exec test -f '{}/cert9.db' ';' -print 2>/dev/null)
      fi
    done
  fi

  remove_host_alias
  flush_dns

  # Reglas firewall inequívocamente PULSIA.
  if command -v ufw >/dev/null 2>&1; then
    mapfile -t nums < <(ufw status numbered 2>/dev/null | sed -n 's/^\[[[:space:]]*\([0-9][0-9]*\)\].*PULSIA Inventario HTTPS.*/\1/p' | sort -rn)
    local n
    for n in "${nums[@]:-}"; do [[ -n "$n" ]] && yes | ufw delete "$n" >/dev/null 2>&1 || true; done
  fi
}

collect_residuals(){
  local f pid cmd pkg
  # Unidades PULSIA.
  for f in "/etc/systemd/system/$APP_SERVICE.service" "/etc/systemd/system/$CADDY_SERVICE.service" "/lib/systemd/system/$APP_SERVICE.service" "/lib/systemd/system/$CADDY_SERVICE.service"; do
    [[ -e "$f" ]] && printf 'unidad:%s\n' "$f"
  done
  systemctl is-active --quiet "$APP_SERVICE.service" 2>/dev/null && printf 'servicio-activo:%s\n' "$APP_SERVICE" || true
  systemctl is-active --quiet "$CADDY_SERVICE.service" 2>/dev/null && printf 'servicio-activo:%s\n' "$CADDY_SERVICE" || true

  # Procesos.
  while IFS= read -r pid; do [[ -n "$pid" ]] && printf 'proceso-caddy:PID-%s\n' "$pid"; done < <(pgrep -x caddy 2>/dev/null || true)
  for f in /proc/[0-9]*; do
    pid="${f##*/}"
    is_pulsia_waitress_pid "$pid" && printf 'proceso-waitress:PID-%s\n' "$pid" || true
  done

  # Dependencias WineHQ instaladas por PULSIA.
  [[ -f "$SYSTEM_CONFIG_DIR/winehq-installed-by-pulsia" ]] &&     printf 'winehq-marcado-pulsia:%s\n' "$SYSTEM_CONFIG_DIR/winehq-installed-by-pulsia"

  # Archivos/directorios de sistema y proyecto generados.
  for f in /opt/pulsia/build-python-*; do
    [[ -e "$f" ]] && printf 'python-build-cliente:%s\n' "$f"
  done
  for f in /opt/pulsia/client-openssl-*; do
    [[ -e "$f" ]] && printf 'openssl-portable-cliente:%s\n' "$f"
  done
  for f in /opt/pulsia/wine-private-*; do
    [[ -e "$f" ]] && printf 'wine-privado-cliente:%s\n' "$f"
  done
  [[ -d "$PROJECT_ROOT/cliente/PULSIA_Inventario_Cliente/.build-wine-windows" ]] &&     printf 'wine-prefix-build:%s\n' "$PROJECT_ROOT/cliente/PULSIA_Inventario_Cliente/.build-wine-windows"
  for f in "$SYSTEM_CONFIG_DIR" "$CADDY_DATA_DIR" "$SYSTEM_CA" "$APP_CLIENT_OUTPUT_DIR" \
           "$PROJECT_ROOT/certs/PULSIA-Inventario-Root-CA.crt" \
           "$PROJECT_ROOT/cliente/PULSIA-Inventario-Root-CA.crt" \
           "$PROJECT_ROOT/cliente/servidor_cliente.ini" \
           "$PROJECT_ROOT/cliente/PULSIA_Inventario_Cliente/servidor_cliente.ini" \
           "$PROJECT_ROOT/cliente/PULSIA_Inventario_Cliente/certificados/PULSIA-Inventario-Root-CA.crt"; do
    [[ -e "$f" ]] && printf 'ruta:%s\n' "$f"
  done

  grep -Eqi '(^|[[:space:]])almacen([[:space:]]|$)' /etc/hosts 2>/dev/null && printf 'dns-local:/etc/hosts contiene almacen\n' || true

  if (( PURGE_ALL_CADDY )); then
    for f in /etc/caddy /var/lib/caddy /var/log/caddy /usr/bin/caddy /usr/local/bin/caddy; do [[ -e "$f" ]] && printf 'caddy-global:%s\n' "$f"; done
    while IFS= read -r pkg; do [[ -n "$pkg" ]] && printf 'paquete-caddy:%s\n' "$pkg"; done < <(dpkg-query -W -f='${binary:Package}\n' 2>/dev/null | awk '/^caddy([:$-]|$)/ {print}' || true)
    find /etc/apt/sources.list.d /etc/apt/keyrings /usr/share/keyrings -maxdepth 1 -iname '*caddy*' -print 2>/dev/null | sed 's#^#repo-caddy:#' || true
    for f in /root /home/*; do
      [[ -d "$f/.local/share/caddy" ]] && printf 'caddy-home:%s\n' "$f/.local/share/caddy"
      [[ -d "$f/.config/caddy" ]] && printf 'caddy-home:%s\n' "$f/.config/caddy"
    done
  fi
}

show_external_dns_info(){
  local ans
  ans="$(getent ahostsv4 almacen 2>/dev/null | awk '{print $1}' | sort -u | paste -sd, - || true)"
  if [[ -n "$ans" ]]; then
    warn "'almacen' todavía resuelve externamente a: $ans"
    warn "No hay entrada local en /etc/hosts; si esa resolución no es deseada, procede de DNS externo/DHCP y debe retirarse en ese servidor DNS."
  else
    ok "No queda resolución local/externa visible para 'almacen'."
  fi
}

echo "============================================================"
echo "PULSIA Inventario Tecnico - DESINSTALACION LINUX VERIFICABLE"
echo "============================================================"
info "Proyecto detectado: $PROJECT_ROOT"
if (( PURGE_ALL_CADDY )); then
  warn "MODO LIMPIEZA TOTAL CADDY: se eliminará Caddy global de esta máquina, incluidos paquete, repositorio, servicios y PKI."
  warn "Use --conservar-caddy-global solo si esta máquina comparte Caddy con otra aplicación."
fi

if (( DIAGNOSTIC_ONLY )); then
  mapfile -t residues < <(collect_residuals)
  if ((${#residues[@]} == 0)); then ok "No se detectan restos locales PULSIA/Caddy."; else printf '%s\n' "${residues[@]}"; fi
  show_external_dns_info
  exit 0
fi

if (( ! ASSUME_YES )); then
  echo
  read -r -p '¿Desea desinstalar? Escriba SI o Y para continuar: ' confirm
  confirm="${confirm^^}"
  [[ "$confirm" == "SI" || "$confirm" == "Y" ]] || { info "Operación cancelada."; exit 2; }
  if (( PURGE_ALL_CADDY )); then
    read -r -p '¿Desea eliminar también Caddy global? Escriba SI o Y para continuar: ' confirm_caddy
    confirm_caddy="${confirm_caddy^^}"
    [[ "$confirm_caddy" == "SI" || "$confirm_caddy" == "Y" ]] || { info "Operación cancelada."; exit 2; }
  fi
fi

for pass in $(seq 1 "$MAX_PASSES"); do
  echo
  info "PASADA DE LIMPIEZA $pass/$MAX_PASSES"
  stop_and_remove_units
  kill_residual_processes
  purge_caddy_global
  purge_pulsia_winehq
  remove_pulsia_files
  systemctl daemon-reload >/dev/null 2>&1 || true
  systemctl reset-failed >/dev/null 2>&1 || true
  sleep 1

  mapfile -t residues < <(collect_residuals)
  if ((${#residues[@]} == 0)); then
    ok "Verificación de la pasada $pass: no quedan restos locales PULSIA/Caddy."
    break
  fi

  warn "Todavía se detectan ${#residues[@]} restos:"
  printf '  - %s\n' "${residues[@]}"
  if (( pass == MAX_PASSES )); then
    echo
    printf '\033[31m[ERROR]\033[0m DESINSTALACIÓN INCOMPLETA tras %s pasadas.\n' "$MAX_PASSES" >&2
    printf 'Restos detectados:\n' >&2
    printf '  - %s\n' "${residues[@]}" >&2
    printf 'Log: %s\n' "$TEMP_LOG" >&2
    exit 3
  fi
  info "Se repetirá la limpieza automáticamente."
done

if (( RESTORE_NETWORK )); then
  warn "La IP estática de una NIC no se revierte a ciegas para no cortar acceso remoto."
  warn "Sí se han eliminado DNS/hosts/cachés creados localmente por PULSIA."
fi

if (( PURGE_DATA )); then
  if (( ASSUME_YES )); then purge="BORRAR DATOS"; else read -r -p 'Escriba BORRAR DATOS para purgar .env, venv, BD, logs y backups: ' purge; fi
  if [[ "${purge:-}" == "BORRAR DATOS" ]]; then
    rm -rf "$PROJECT_ROOT/.venv" "$PROJECT_ROOT/data" "$PROJECT_ROOT/logs" "$PROJECT_ROOT/backups" "$PROJECT_ROOT/certs"
    rm -f "$PROJECT_ROOT/.env"
    ok "Datos locales purgados."
  fi
fi

show_external_dns_info

echo
echo "============================================================"
echo "DESINSTALACION LOCAL VERIFICADA Y COMPLETA"
echo "No quedan servicios/procesos/PKI/CA/hosts/paquetes Caddy locales detectables."
echo "Proyecto fuente conservado: $PROJECT_ROOT"
echo "Log: $TEMP_LOG"
echo "============================================================"
