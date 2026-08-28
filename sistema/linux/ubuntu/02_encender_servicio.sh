#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/lib/pulsia_common.sh"
require_root
require_service_install
info "Iniciando PULSIA Inventario..."
systemctl start "$SERVICE_NAME"
systemctl start "$CADDY_SERVICE_NAME"
sleep 1
service_active "$SERVICE_NAME" || { show_failed_logs "$SERVICE_NAME"; fail "$SERVICE_NAME no arrancó."; }
service_active "$CADDY_SERVICE_NAME" || { show_failed_logs "$CADDY_SERVICE_NAME"; fail "$CADDY_SERVICE_NAME no arrancó."; }
ok "Servicio y Caddy activos."
ss -ltn | grep -E '(:80|:443|:8080)' || true
