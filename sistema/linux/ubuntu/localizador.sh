#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
OUTPUT="$SCRIPT_DIR/conexion.sh"
LOGIN_PATH="/cuenta/login/"

# Este script es exclusivo del servidor PULSIA.
if ! systemctl list-unit-files pulsia-inventario.service >/dev/null 2>&1 && [[ ! -f /etc/systemd/system/pulsia-inventario.service ]]; then
  echo "[ERROR] localizador.sh debe ejecutarse en el servidor PULSIA Inventario ya instalado." >&2
  exit 2
fi

# Se prioriza la interfaz de la ruta por defecto.
IFACE="$(ip route show default 2>/dev/null | awk '/default/ {print $5; exit}')"
SERVER_IP=""
if [[ -n "$IFACE" ]]; then
  SERVER_IP="$(ip -o -4 addr show dev "$IFACE" scope global 2>/dev/null | awk '{split($4,a,"/"); print a[1]; exit}')"
fi
if [[ -z "$SERVER_IP" ]]; then
  SERVER_IP="$(ip -o -4 addr show scope global 2>/dev/null | awk '{split($4,a,"/"); print a[1]; exit}')"
fi

if [[ -z "$SERVER_IP" ]]; then
  echo "[ERROR] No se pudo detectar una IPv4 LAN del servidor." >&2
  exit 1
fi

# Rechazar direcciones que claramente no sirven para un cliente LAN.
case "$SERVER_IP" in
  127.*|169.254.*)
    echo "[ERROR] La IP detectada no es una IP LAN utilizable: $SERVER_IP" >&2
    exit 1
    ;;
esac

URL="https://${SERVER_IP}${LOGIN_PATH}"

cat > "$OUTPUT" <<EOF
#!/usr/bin/env bash
set -e
URL="$URL"

if command -v xdg-open >/dev/null 2>&1; then
  exec xdg-open "\$URL"
elif command -v gio >/dev/null 2>&1; then
  exec gio open "\$URL"
elif command -v sensible-browser >/dev/null 2>&1; then
  exec sensible-browser "\$URL"
else
  echo "Abra esta dirección en su navegador:"
  echo "\$URL"
fi
EOF

chmod 755 "$OUTPUT"

# Si se ejecutó mediante sudo, devolver el fichero generado al usuario real.
if [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != "root" ]]; then
  chown "$SUDO_USER:$(id -gn "$SUDO_USER")" "$OUTPUT" 2>/dev/null || true
fi

echo "[OK] IP del servidor detectada: $SERVER_IP"
echo "[OK] Script generado: $OUTPUT"
echo "[INFO] El script conexion.sh abrirá directamente:"
echo "       $URL"
echo "[INFO] Copie conexion.sh al equipo Linux desde el que quiera acceder."
