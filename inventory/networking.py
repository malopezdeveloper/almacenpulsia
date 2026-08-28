from __future__ import annotations
import json, os, subprocess, sys, urllib.request, urllib.error
from pathlib import Path
from django.conf import settings
from django.utils import timezone
from .models import NetworkReservationRequest, AuditLog


def _helper_path():
    return Path(settings.BASE_DIR)/"sistema"/"common"/"network_dns.py"


def current_network():
    p=subprocess.run([sys.executable,str(_helper_path()),"current"],capture_output=True,text=True,timeout=20)
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or "No se pudo detectar la red actual")
    data=json.loads(p.stdout)
    if not data.get("ip") or not data.get("mac"):
        raise RuntimeError("No se pudo obtener simultáneamente la IP y MAC de la interfaz activa")
    if str(data.get("ip","" )).startswith("169.254."):
        raise RuntimeError("La interfaz activa tiene una dirección APIPA 169.254.x.x y no es válida para una reserva")
    return data


def _dhcp_request(payload):
    """Solicita la reserva a un endpoint DHCP autorizado. No ejecuta comandos arbitrarios."""
    url=(os.getenv("PULSIA_DHCP_RESERVATION_URL") or "").strip()
    token=(os.getenv("PULSIA_DHCP_API_TOKEN") or "").strip()
    if not url:
        return False,"No está configurado PULSIA_DHCP_RESERVATION_URL. La solicitud queda pendiente para el administrador DHCP.",{}
    body=json.dumps(payload).encode("utf-8")
    headers={"Content-Type":"application/json","Accept":"application/json","User-Agent":"PULSIA-Inventario/1"}
    if token: headers["Authorization"]="Bearer "+token
    req=urllib.request.Request(url,data=body,headers=headers,method="POST")
    try:
        with urllib.request.urlopen(req,timeout=12) as r:
            raw=r.read(1024*1024).decode("utf-8","replace")
            response=json.loads(raw) if raw.strip() else {}
            ok=200 <= r.status < 300 and response.get("success",True) is not False
            return ok,(response.get("message") or f"DHCP respondió HTTP {r.status}"),response
    except urllib.error.HTTPError as e:
        raw=e.read(20000).decode("utf-8","replace")
        return False,f"El servicio DHCP respondió HTTP {e.code}: {raw[:1000]}",{}
    except Exception as e:
        return False,f"No se pudo contactar con el servicio DHCP autorizado: {e}",{}


def _dns_update(net):
    dns_server=(os.getenv("PULSIA_DNS_SERVER") or "").strip()
    zone=(os.getenv("PULSIA_DNS_ZONE") or net.get("zone") or "").strip()
    host=(os.getenv("PULSIA_DNS_HOST") or "almacen").strip()
    key=(os.getenv("PULSIA_DNS_TSIG_KEY_FILE") or "").strip()
    if not dns_server:
        candidates=[x for x in net.get("dns",[]) if x and not str(x).startswith("127.")]
        dns_server=candidates[0] if candidates else ""
    if not (dns_server and zone and key and Path(key).exists()):
        return False,"DNS RFC2136 no configurado completamente (servidor, zona y clave TSIG)."
    cmd=[sys.executable,str(_helper_path()),"update","--server",dns_server,"--zone",zone,"--host",host,"--address",net["ip"],"--key-file",key]
    p=subprocess.run(cmd,capture_output=True,text=True,timeout=20)
    if p.returncode:
        return False,p.stderr.strip() or "El DNS rechazó la actualización"
    return True,f"Registro DNS actualizado: {host}.{zone} -> {net['ip']}"


def request_current_ip_reservation(user):
    net=current_network()
    payload={
        "hostname":net.get("hostname") or os.getenv("COMPUTERNAME") or "almacen",
        "requested_hostname":os.getenv("PULSIA_DNS_HOST") or "almacen",
        "ip":net["ip"],"prefix":net.get("prefix"),"gateway":net.get("gateway"),
        "mac":net.get("mac"),"interface":net.get("interface"),"platform":net.get("platform"),
    }
    req=NetworkReservationRequest.objects.create(
        ip_address=net["ip"],prefix_length=int(net.get("prefix") or 24),gateway=net.get("gateway") or None,
        mac_address=net.get("mac") or "",interface_name=net.get("interface") or "",hostname=payload["hostname"],
        platform=net.get("platform") or "",requested_by=user,details={"network":net},
    )
    dhcp_ok,dhcp_msg,dhcp_response=_dhcp_request(payload)
    dns_ok,dns_msg=_dns_update(net)
    if not dhcp_ok:
        pending=Path(settings.BASE_DIR)/"data"/"dhcp-reserva-pendiente.json"
        pending.parent.mkdir(parents=True,exist_ok=True)
        pending.write_text(json.dumps({**payload,"requested_at":timezone.now().isoformat()},ensure_ascii=False,indent=2),encoding="utf-8")
    req.dhcp_reserved=dhcp_ok; req.dns_updated=dns_ok
    req.status="applied" if dhcp_ok and dns_ok else ("partial" if dhcp_ok or dns_ok else "pending")
    req.message=f"DHCP: {dhcp_msg}\nDNS: {dns_msg}"
    req.details={"network":net,"dhcp_response":dhcp_response,"dhcp_message":dhcp_msg,"dns_message":dns_msg}
    req.completed_at=timezone.now() if req.status in {"applied","partial"} else None
    req.save(update_fields=["dhcp_reserved","dns_updated","status","message","details","completed_at"])
    AuditLog.objects.create(user=user,action="network_ip_reservation_requested",object_type="Network",object_id=net["ip"],details={"mac":net.get("mac"),"dhcp_reserved":dhcp_ok,"dns_updated":dns_ok,"status":req.status})
    return req
