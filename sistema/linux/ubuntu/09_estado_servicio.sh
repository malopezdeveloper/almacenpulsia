#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/lib/pulsia_common.sh"
printf '============================================================\n'
printf 'PULSIA Inventario Técnico - ESTADO\n'
printf '============================================================\n'
for svc in "$SERVICE_NAME" "$CADDY_SERVICE_NAME"; do
  if systemctl is-active --quiet "$svc" 2>/dev/null; then ok "$svc: active (running)"
  else warn "$svc: $(systemctl is-active "$svc" 2>/dev/null || echo no-instalado)"; fi
done
printf '\nRed:\n'
ip -o -4 addr show scope global 2>/dev/null | awk '{print "  "$2": "$4}' || true
LAN_IP="$(ip -o -4 addr show scope global 2>/dev/null | awk '{split($4,a,"/"); print a[1]; exit}')"
printf '\nAdministración remota:\n'
if systemctl is-active --quiet ssh 2>/dev/null; then ok "ssh: active (running)"; else warn "ssh: no activo"; fi
SSH_PORTS="$(ss -ltnp 2>/dev/null | grep -E '(:22[[:space:]]|:22$)' || true)"
[[ -n "$SSH_PORTS" ]] && printf '%s\n' "$SSH_PORTS" || warn "No se detecta escucha SSH en TCP/22 (puede usar otro puerto)."
[[ -n "$LAN_IP" ]] && printf '  SSH sugerido: ssh %s@%s\n' "${SUDO_USER:-<usuario-linux>}" "$LAN_IP"
printf '\nPuertos:\n'
ss -ltnp 2>/dev/null | grep -E '(:80|:443|:8080)' || echo "  sin escuchas 80/443/8080"
printf '\nHTTPS / backend:\n'
curl -sS -H 'Host: almacen' -H 'X-Forwarded-Proto: https' -o /dev/null -w '  Backend 127.0.0.1:8080 -> HTTP %{http_code}\n' "http://127.0.0.1:8080/" 2>/dev/null || echo "  Backend sin respuesta"
if [[ -n "$LAN_IP" ]]; then
  CA_FILE="$PROJECT_ROOT/certs/PULSIA-Inventario-Root-CA.crt"
  if [[ -f "$CA_FILE" ]]; then
    curl --cacert "$CA_FILE" -sS -o /dev/null -w "  https://$LAN_IP -> HTTPS %{http_code}\n" "https://$LAN_IP/" 2>/dev/null || echo "  Acceso HTTPS LAN por IP sin respuesta"
  else
    echo "  CA PULSIA no disponible para validar HTTPS."
  fi
  curl -sS -o /dev/null -w "  http://$LAN_IP -> redirect HTTP %{http_code}\n" "http://$LAN_IP/" 2>/dev/null || true
  printf '  URL clientes: https://%s\n' "$LAN_IP"
else
  warn "No se detectó IP LAN."
fi
printf '\nVersiones:\n'
[[ -x "$PROJECT_ROOT/.venv/bin/python" ]] && "$PROJECT_ROOT/.venv/bin/python" --version || true
command -v caddy >/dev/null 2>&1 && caddy version || true
[[ -f "$SYSTEM_CONFIG_DIR/private-wine-installed-by-pulsia" ]] && sed 's/^/  /' "$SYSTEM_CONFIG_DIR/private-wine-installed-by-pulsia"
