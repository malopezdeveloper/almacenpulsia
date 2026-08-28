#!/usr/bin/env bash
set -Eeuo pipefail

ok(){ printf '\033[32m[OK]\033[0m %s\n' "$*"; }
info(){ printf '\033[36m[INFO]\033[0m %s\n' "$*"; }
warn(){ printf '\033[33m[AVISO]\033[0m %s\n' "$*"; }
fail(){ printf '\033[31m[ERROR]\033[0m %s\n' "$*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || exec sudo -E bash "$0" "$@"
[[ -r /etc/os-release ]] || fail "No se puede identificar el sistema operativo."
. /etc/os-release
[[ "${ID:-}" == "ubuntu" ]] || fail "Use este script únicamente en Ubuntu Server. Detectado: ${PRETTY_NAME:-desconocido}"

export DEBIAN_FRONTEND=noninteractive
info "Instalando/asegurando OpenSSH Server para administración remota..."
apt-get update
apt-get install -y --no-install-recommends openssh-server iproute2 ca-certificates sudo
install -d -m 0755 /run/sshd
/usr/sbin/sshd -t || fail "La configuración actual de sshd no supera sshd -t. No se modifica automáticamente para evitar bloquear el servidor."
systemctl enable --now ssh
systemctl is-active --quiet ssh || fail "El servicio SSH no está activo."

IFACE="$(ip route show default 2>/dev/null | awk '/default/ {print $5; exit}')"
IP=""; CIDR=""
if [[ -n "$IFACE" ]]; then
  CIDR="$(ip -o -4 addr show dev "$IFACE" scope global 2>/dev/null | awk '{print $4; exit}')"
  IP="${CIDR%%/*}"
fi
LAN_NET=""
if [[ -n "$CIDR" ]] && command -v python3 >/dev/null 2>&1; then
  LAN_NET="$(python3 - "$CIDR" <<'PYNET'
import ipaddress,sys
print(ipaddress.ip_interface(sys.argv[1]).network)
PYNET
)"
fi
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q '^Status: active'; then
  if [[ -n "$LAN_NET" ]]; then
    ufw allow from "$LAN_NET" to any port 22 proto tcp comment 'PULSIA SSH LAN' >/dev/null || true
    ok "UFW: SSH/TCP 22 permitido desde $LAN_NET."
  else
    warn "UFW está activo y no se determinó la LAN. Revise manualmente que TCP/22 esté permitido."
  fi
elif command -v nft >/dev/null 2>&1; then
  warn "nftables detectado. No se alteran políticas corporativas automáticamente; compruebe TCP/22 desde la LAN."
fi

SSH_USER="${SUDO_USER:-$(logname 2>/dev/null || true)}"
[[ -n "$SSH_USER" && "$SSH_USER" != root ]] || SSH_USER="<usuario-linux>"
PASS_AUTH="$(sshd -T 2>/dev/null | awk '$1=="passwordauthentication"{print $2; exit}')"
ROOT_AUTH="$(sshd -T 2>/dev/null | awk '$1=="permitrootlogin"{print $2; exit}')"
ok "SSH activo y habilitado al arranque."
[[ -n "$IP" ]] && info "Acceso remoto sugerido: ssh $SSH_USER@$IP" || warn "No se pudo detectar la IP LAN."
info "PasswordAuthentication efectivo: ${PASS_AUTH:-desconocido}"
info "PermitRootLogin efectivo: ${ROOT_AUTH:-desconocido}"
if [[ "$PASS_AUTH" == no ]]; then
  warn "La autenticación SSH por contraseña está deshabilitada por la política actual. Use clave SSH o habilítela conscientemente en sshd_config.d."
fi
info "El script NO habilita login SSH de root ni debilita la política SSH existente."
