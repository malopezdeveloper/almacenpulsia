#!/usr/bin/env bash
set -u

DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

run_script() {
    local script="$1"
    local path="$DIR/$script"
    if [[ ! -f "$path" ]]; then
        echo "[ERROR] No existe: $path"
        return 1
    fi
    chmod +x "$path" 2>/dev/null || true
    echo
    echo "[INFO] Ejecutando $script"
    sudo "$path"
    local rc=$?
    echo
    echo "[INFO] Finalizado con código $rc."
    read -r -p "Pulse ENTER para volver al menú..." _
}

while true; do
    clear
    cat <<'EOF'
============================================================
                 PULSIA ALMACÉN - MENÚ
============================================================
 1) Configurar acceso remoto
 2) Instalar servicio
 3) Encender servicio
 4) Reiniciar servicio
 5) Parar servicio
 6) Desinstalar servicio
 7) Crear primer usuario
 8) Actualizar solo programa
 9) Actualizar programa y base de datos
10) Actualización estructural del servidor
11) Ver estado del servicio
12) Volver atrás una actualización
 0) Salir
============================================================
EOF
    read -r -p "Seleccione una opción: " option
    case "$option" in
        1) run_script "00_configurar_acceso_remoto.sh" ;;
        2) run_script "01_instalar_servicio.sh" ;;
        3) run_script "02_encender_servicio.sh" ;;
        4) run_script "03_reiniciar_servicio.sh" ;;
        5) run_script "04_parar_servicio.sh" ;;
        6) run_script "05_desinstalar_servicio.sh" ;;
        7) run_script "06_crear_primer_usuario.sh" ;;
        8) run_script "07_actualizar_solo_programa.sh" ;;
        9) run_script "08_actualizar_programa_y_bd.sh" ;;
        10) run_script "09_actualizar_servidor_estructural.sh" ;;
        11) run_script "09_estado_servicio.sh" ;;
        12) run_script "10_volver_atras_actualizacion.sh" ;;
        0) echo "Saliendo."; exit 0 ;;
        *) echo "Opción no válida."; sleep 1 ;;
    esac
done
