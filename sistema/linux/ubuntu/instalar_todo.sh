#!/usr/bin/env bash
set -Eeuo pipefail
DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
printf '[AVISO] instalar_todo.sh instala solo el servidor. Los clientes acceden por navegador; use localizador.sh para generar conexion.sh.\n'
printf '[INFO] Se prepara primero el acceso remoto SSH y después se instala el servicio.\n'
"$DIR/00_configurar_acceso_remoto.sh"
exec "$DIR/01_instalar_servicio.sh" "$@"
