#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/lib/pulsia_common.sh"
require_root
require_service_install
info "Deteniendo Caddy y PULSIA Inventario..."
systemctl stop "$CADDY_SERVICE_NAME" || true
systemctl stop "$SERVICE_NAME" || true
service_active "$SERVICE_NAME" && fail "$SERVICE_NAME sigue activo."
service_active "$CADDY_SERVICE_NAME" && fail "$CADDY_SERVICE_NAME sigue activo."
ok "Servicios detenidos."
ss -ltn | grep -E '(:443|:8080)' && warn "Quedan procesos escuchando en 443/8080; pueden pertenecer a otra aplicación." || true
