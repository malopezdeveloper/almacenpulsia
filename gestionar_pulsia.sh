#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$ROOT" != "/almacen" && "${PULSIA_ALLOW_NONSTANDARD_ROOT:-0}" != "1" ]]; then
  echo "[ERROR] Este gestor está preparado para /almacen. Ruta actual: $ROOT"
  echo "        Para laboratorio: PULSIA_ALLOW_NONSTANDARD_ROOT=1 sudo -E ./gestionar_pulsia.sh"
  exit 1
fi
if [[ ${EUID} -ne 0 ]]; then
  exec sudo -E "$0" "$@"
fi
APP_USER="${PULSIA_APP_USER:-${SUDO_USER:-pulsia}}"
id "$APP_USER" >/dev/null 2>&1 || { echo "[ERROR] No existe el usuario $APP_USER"; exit 1; }
APP_GROUP="$(id -gn "$APP_USER")"

apply_permissions(){
  echo "[INFO] Ajustando propietario a $APP_USER:$APP_GROUP..."
  chown -R "$APP_USER:$APP_GROUP" "$ROOT"

  # No destruir permisos internos del virtualenv ya instalado.
  find "$ROOT" -path "$ROOT/.venv" -prune -o -type d -exec chmod 0750 {} +
  find "$ROOT" -path "$ROOT/.venv" -prune -o -type f -exec chmod 0640 {} +

  find "$ROOT/sistema" -type f -name '*.sh' -exec chmod 0750 {} + 2>/dev/null || true
  chmod 0750 "$ROOT/manage.py" "$ROOT/gestionar_pulsia.sh" 2>/dev/null || true
  [[ -f "$ROOT/.env" ]] && chmod 0600 "$ROOT/.env"
  [[ -f "$ROOT/data/inventario.sqlite3" ]] && chmod 0600 "$ROOT/data/inventario.sqlite3"
  [[ -d "$ROOT/data" ]] && chmod 0750 "$ROOT/data"
  [[ -d "$ROOT/logs" ]] && chmod 0750 "$ROOT/logs"
  [[ -d "$ROOT/backups" ]] && chmod 0750 "$ROOT/backups"
  [[ -d "$ROOT/certs" ]] && chmod 0750 "$ROOT/certs"

  echo "[OK] Permisos PULSIA aplicados sin modificar los ejecutables internos de .venv."
}

choose_distro(){
  while true; do
    echo
    echo "========== PULSIA · GESTIÓN DEL SISTEMA =========="
    echo "1) Ubuntu"
    echo "2) Debian"
    echo "0) Salir"
    read -r -p "Seleccione sistema: " opt
    case "$opt" in
      1) DISTRO=ubuntu; break;;
      2) DISTRO=debian; break;;
      0) exit 0;;
      *) echo "Opción no válida.";;
    esac
  done
}

script_menu(){
  local dir="$ROOT/sistema/linux/$DISTRO"
  [[ -d "$dir" ]] || { echo "[ERROR] No existe $dir"; exit 1; }
  while true; do
    mapfile -t scripts < <(find "$dir" -maxdepth 1 -type f -name '*.sh' -printf '%f\n' | sort)
    echo
    echo "========== ${DISTRO^^} · SCRIPTS PULSIA =========="
    local i=1
    for script in "${scripts[@]}"; do printf '%2d) %s\n' "$i" "$script"; ((i++)); done
    echo " r) Reaplicar permisos"
    echo " s) Cambiar Ubuntu/Debian"
    echo " 0) Salir"
    read -r -p "Seleccione opción: " opt
    case "$opt" in
      0) exit 0;;
      r|R) apply_permissions;;
      s|S) choose_distro; dir="$ROOT/sistema/linux/$DISTRO";;
      *)
        if [[ "$opt" =~ ^[0-9]+$ ]] && (( opt >= 1 && opt <= ${#scripts[@]} )); then
          target="$dir/${scripts[$((opt-1))]}"
          echo "[INFO] Ejecutando $target"
          bash "$target"
        else
          echo "Opción no válida."
        fi
        ;;
    esac
  done
}

apply_permissions
choose_distro
script_menu
