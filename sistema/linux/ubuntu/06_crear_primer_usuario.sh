#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/lib/pulsia_common.sh"
require_root
require_service_install

VENV="$PROJECT_ROOT/.venv"
DATA="$PROJECT_ROOT/data"
TOKEN_FILE="$DATA/.gestor-bootstrap-token"
URL_FILE="$SYSTEM_CONFIG_DIR/acceso-inicial-gestor.url"

[[ -x "$VENV/bin/python" ]] || fail "No existe el entorno Python del servicio. Ejecute 01_instalar_servicio.sh."
[[ -f "$PROJECT_ROOT/manage.py" ]] || fail "No se encuentra manage.py."

OWNER="$(stat -c '%U' "$DATA" 2>/dev/null || true)"
[[ -n "$OWNER" && "$OWNER" != UNKNOWN ]] || OWNER="$(run_user)"
id "$OWNER" >/dev/null 2>&1 || OWNER=root

printf '\n==============================================\n'
printf ' CONFIGURACIÓN DEL PRIMER USUARIO GESTOR\n'
printf '==============================================\n\n'
printf 'Seleccione cómo desea definir la contraseña del Gestor:\n\n'
printf '  1) Crear/configurar el Gestor ahora y escribir la contraseña en esta terminal.\n'
printf '     La contraseña se solicita de forma oculta y NO se pasa como argumento.\n\n'
printf '  2) Crear/preparar el Gestor y establecer la contraseña desde la web.\n'
printf '     Se generará un enlace temporal de un solo uso (15 minutos).\n\n'
printf '  3) Cancelar.\n\n'
printf '  4) Restablecer la contraseña de un Gestor existente.\n'
printf '     No es necesario conocer la contraseña anterior y NO crea usuarios nuevos.\n\n'

while true; do
  read -r -p 'Opción [1/2/3/4, predeterminada 1]: ' OPTION
  OPTION="${OPTION:-1}"
  case "$OPTION" in
    1|2|3|4) break ;;
    *) warn "Opción no válida. Introduzca 1, 2, 3 o 4." ;;
  esac
done

cd "$PROJECT_ROOT"

case "$OPTION" in
  1)
    rm -f "$TOKEN_FILE" "$URL_FILE"
    info "Creación/configuración interactiva del usuario Gestor."
    info "La contraseña no se mostrará mientras la escribe."
    sudo -u "$OWNER" -H "$VENV/bin/python" manage.py configurar_gestor
    ok "Configuración del Gestor finalizada."
    printf '\nYa puede iniciar sesión desde la página de acceso con las credenciales creadas.\n\n'
    ;;

  2)
    warn "Esta acción crea/localiza el Gestor y genera un NUEVO acceso inicial de un solo uso."
    warn "Si el Gestor ya existía, su contraseña utilizable quedará invalidada según el flujo de bootstrap de la aplicación."

    rm -f "$TOKEN_FILE" "$URL_FILE"
    sudo -u "$OWNER" -H "$VENV/bin/python" manage.py preparar_acceso_gestor \
      --token-file "$TOKEN_FILE" --minutes 15

    [[ -s "$TOKEN_FILE" ]] || fail "No se generó el token inicial."
    TOKEN="$(tr -d '\r\n' < "$TOKEN_FILE")"
    URL="https://${CADDY_SITE}/acceso-inicial/${TOKEN}/"
    printf '%s\n' "$URL" > "$URL_FILE"
    chmod 600 "$URL_FILE" "$TOKEN_FILE" || true

    ok "Primer Gestor preparado."
    printf '\nURL de acceso inicial (válida durante 15 minutos):\n%s\n\n' "$URL"
    info "También se ha guardado temporalmente en: $URL_FILE"
    warn "Use la URL una sola vez y no la comparta."
    ;;

  3)
    info "Operación cancelada. No se ha modificado ningún usuario."
    exit 0
    ;;

  4)
    rm -f "$TOKEN_FILE" "$URL_FILE"
    warn "Va a RESTABLECER la contraseña de un Gestor existente."
    warn "No necesita conocer la contraseña anterior. No se crearán usuarios nuevos."
    info "La nueva contraseña no se mostrará mientras la escribe."
    sudo -u "$OWNER" -H "$VENV/bin/python" manage.py configurar_gestor --reset-password
    ok "Contraseña del Gestor restablecida correctamente."
    printf '\nYa puede iniciar sesión con la nueva contraseña.\n\n'
    ;;
esac
