"""
Servidor simple para recibir sugerencias del Trading Agent.

Uso:
  set FEEDBACK_WEBHOOK_TOKEN=tu_token
  set FEEDBACK_SAVE_DIR=feedback
  set FEEDBACK_LIST_ALLOWED_IPS=TU_IP_PUBLICA
  # alternativa local estricta:
  # set FEEDBACK_LIST_LOCAL_ONLY=true
  python feedback_server.py

URL ejemplo:
  https://tu-dominio.com/feedback?key=tu_token
"""

import json
import os
import ipaddress
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs


SAVE_DIR = os.getenv("FEEDBACK_SAVE_DIR", "feedback")
TOKEN = (os.getenv("FEEDBACK_WEBHOOK_TOKEN", "") or "").strip()
HOST = os.getenv("FEEDBACK_HOST", "0.0.0.0")

def _get_port():
    # decidimos en que "puerta" (puerto) va a escuchar el servidor.
    port_raw = (os.getenv("PORT") or "").strip()
    if port_raw:
        try:
            return int(port_raw)
        except ValueError:
            pass
    fallback = (os.getenv("FEEDBACK_PORT") or "8080").strip()
    try:
        return int(fallback)
    except ValueError:
        return 8080

PORT = _get_port()
MAX_BODY_BYTES = int(os.getenv("FEEDBACK_MAX_BYTES", "32768"))


def _env_flag(name: str, default: bool = False) -> bool:
    # convierte texto de variables de entorno en True/False.
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on", "si", "sí")


def _parse_allowed_ip_networks(raw: str):
    # transforma "1.2.3.4,10.0.0.0/24" en reglas de red válidas.
    networks = []
    for part in (raw or "").split(","):
        item = part.strip()
        if not item:
            continue
        try:
            if "/" in item:
                networks.append(ipaddress.ip_network(item, strict=False))
                continue
            ip_obj = ipaddress.ip_address(item)
            mask = 32 if ip_obj.version == 4 else 128
            networks.append(ipaddress.ip_network(f"{ip_obj}/{mask}", strict=False))
        except ValueError:
            print(f"Aviso: FEEDBACK_LIST_ALLOWED_IPS contiene IP/CIDR inválido: {item}")
    return networks


LIST_LOCAL_ONLY = _env_flag("FEEDBACK_LIST_LOCAL_ONLY", False)
LIST_ALLOWED_IPS_RAW = (os.getenv("FEEDBACK_LIST_ALLOWED_IPS", "") or "").strip()
LIST_ALLOWED_NETWORKS = _parse_allowed_ip_networks(LIST_ALLOWED_IPS_RAW)


def _json_response(handler, status_code: int, payload: dict):
    # empaquetamos la respuesta en JSON y la devolvemos al cliente.
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status_code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)



def _check_token(parsed) -> bool:
    # comprobamos la llave secreta para evitar que cualquiera envie datos.
    if not TOKEN:
        return True
    query = parse_qs(parsed.query)
    key = (query.get("key") or [""])[0]
    return key == TOKEN


def _parse_limit(parsed, default=50, max_limit=200):
    # leemos cuantas sugerencias pidio el usuario, con limites seguros.
    query = parse_qs(parsed.query)
    raw = (query.get("limit") or [""])[0]
    try:
        value = int(raw)
    except ValueError:
        value = default
    if value <= 0:
        return default
    return min(value, max_limit)


def _read_recent_feedback(limit: int):
    # abrimos archivos de feedback y devolvemos lo mas nuevo primero.
    if not os.path.isdir(SAVE_DIR):
        return []

    try:
        files = [
            name for name in os.listdir(SAVE_DIR)
            if name.startswith("feedback_") and name.endswith(".jsonl")
        ]
        files.sort(reverse=True)
    except Exception:
        return []

    items = []
    for name in files:
        path = os.path.join(SAVE_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            continue

        # Procesa desde el final para traer lo más reciente primero.
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                continue
            if len(items) >= limit:
                return items
    return items


def _get_client_ip(handler):
    # intentamos detectar la IP real del cliente (directa o via proxy).
    xff_raw = (handler.headers.get("X-Forwarded-For") or "").strip()
    if xff_raw:
        candidate = xff_raw.split(",", 1)[0].strip()
    else:
        candidate = (handler.client_address[0] if handler.client_address else "") or ""
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        return None


def _is_feedback_list_client_allowed(handler) -> bool:
    # decide si este cliente puede leer /feedback/list.
    client_ip = _get_client_ip(handler)
    if client_ip is None:
        return False

    if LIST_ALLOWED_NETWORKS:
        return any(client_ip in network for network in LIST_ALLOWED_NETWORKS)

    if LIST_LOCAL_ONLY:
        return client_ip.is_loopback

    return True


class FeedbackHandler(BaseHTTPRequestHandler):
    # esta clase atiende las peticiones que llegan por internet.
    def do_GET(self):
        # esta funcion sirve para atender peticiones GET del servidor.
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/health"):
            _json_response(self, 200, {"ok": True})
            return
        if parsed.path == "/feedback/list":
            # Esta ruta devuelve la lista de sugerencias guardadas.
            if not _is_feedback_list_client_allowed(self):
                _json_response(self, 404, {"ok": False, "error": "not_found"})
                return
            if not _check_token(parsed):
                _json_response(self, 401, {"ok": False, "error": "unauthorized"})
                return
            limit = _parse_limit(parsed)
            items = _read_recent_feedback(limit)
            _json_response(self, 200, {"ok": True, "count": len(items), "items": items})
            return
        _json_response(self, 404, {"ok": False, "error": "not_found"})

    def do_POST(self):
        # esta funcion sirve para atender peticiones POST del servidor.
        parsed = urlparse(self.path)
        if parsed.path != "/feedback":
            _json_response(self, 404, {"ok": False, "error": "not_found"})
            return

        # Primero validamos la llave de seguridad.
        if not _check_token(parsed):
            _json_response(self, 401, {"ok": False, "error": "unauthorized"})
            return

        length_header = self.headers.get("Content-Length", "0")
        try:
            length = int(length_header)
        except ValueError:
            length = 0

        # Si no hay contenido o es demasiado grande, se rechaza para proteger el servidor.
        if length <= 0:
            _json_response(self, 400, {"ok": False, "error": "empty_body"})
            return
        if length > MAX_BODY_BYTES:
            _json_response(self, 413, {"ok": False, "error": "payload_too_large"})
            return

        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            _json_response(self, 400, {"ok": False, "error": "invalid_json"})
            return

        # "message" es obligatorio: sin texto, no hay sugerencia valida.
        message = (payload.get("message") or "").strip()
        subject = (payload.get("subject") or "").strip()
        if not message:
            _json_response(self, 400, {"ok": False, "error": "missing_message"})
            return

        record = {
            "received_at": datetime.utcnow().isoformat() + "Z",
            "subject": subject,
            "message": message,
            "symbol": payload.get("symbol") or "",
            "strategy": payload.get("strategy") or "",
            "timeframe": payload.get("timeframe") or "",
            "client_timestamp": payload.get("timestamp") or "",
        }

        try:
            # Guardamos cada sugerencia en una linea JSON para poder leerlas luego facilmente.
            os.makedirs(SAVE_DIR, exist_ok=True)
            filename = f"feedback_{datetime.utcnow().strftime('%Y-%m-%d')}.jsonl"
            path = os.path.join(SAVE_DIR, filename)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception:
            _json_response(self, 500, {"ok": False, "error": "save_failed"})
            return

        _json_response(self, 200, {"ok": True})

    def log_message(self, format, *args):
        # dejamos esto vacio para que la consola no se llene de mensajes HTTP.
        # Reduce ruido en consola; comenta esta función si quieres logs HTTP.
        return


def main():
    # esta funcion sirve para arrancar todo el programa.
    # Creamos el servidor y lo dejamos escuchando sin parar.
    server = ThreadingHTTPServer((HOST, PORT), FeedbackHandler)
    print(f"Feedback server escuchando en http://{HOST}:{PORT}/feedback")
    print("Endpoints activos: GET /health, POST /feedback, GET /feedback/list")
    if TOKEN:
        print("Token activo: se requiere ?key=TOKEN")
    else:
        print("Aviso: sin token; el endpoint acepta cualquier POST.")
    if LIST_ALLOWED_NETWORKS:
        print(f"Acceso /feedback/list restringido por IP: {LIST_ALLOWED_IPS_RAW}")
    elif LIST_LOCAL_ONLY:
        print("Acceso /feedback/list restringido a localhost (loopback).")
    else:
        print("Acceso /feedback/list sin restricción de IP (además del token, si aplica).")
    server.serve_forever()


if __name__ == "__main__":
    main()


