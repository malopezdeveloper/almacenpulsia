import json, socket
from pathlib import Path

SOCKET_PATH=Path("/run/pulsia-inventario/storage-admin.sock")

def request_storage_admin(payload, timeout=15):
    data=(json.dumps(payload,ensure_ascii=False)+"\n").encode("utf-8")
    if not SOCKET_PATH.exists():
        raise RuntimeError("El servicio privilegiado de almacenamiento no está disponible. Reinstale/actualice los scripts Linux.")
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(str(SOCKET_PATH))
        sock.sendall(data)
        buf=b""
        while b"\n" not in buf and len(buf)<65536:
            chunk=sock.recv(4096)
            if not chunk: break
            buf+=chunk
    if not buf: raise RuntimeError("El servicio de almacenamiento no respondió.")
    result=json.loads(buf.split(b"\n",1)[0].decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError(result.get("error") or "Operación de almacenamiento rechazada.")
    return result
