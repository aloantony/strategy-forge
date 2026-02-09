"""
Servidor simple para recibir sugerencias del Trading Agent.

Uso:
  set FEEDBACK_WEBHOOK_TOKEN=tu_token
  set FEEDBACK_SAVE_DIR=feedback
  python feedback_server.py

URL ejemplo:
  https://tu-dominio.com/feedback?key=tu_token
"""

import json
import os
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs


SAVE_DIR = os.getenv("FEEDBACK_SAVE_DIR", "feedback")
TOKEN = (os.getenv("FEEDBACK_WEBHOOK_TOKEN", "") or "").strip()
HOST = os.getenv("FEEDBACK_HOST", "0.0.0.0")

def _get_port():
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


def _json_response(handler, status_code: int, payload: dict):
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status_code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class FeedbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/health"):
            _json_response(self, 200, {"ok": True})
            return
        _json_response(self, 404, {"ok": False, "error": "not_found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/feedback":
            _json_response(self, 404, {"ok": False, "error": "not_found"})
            return

        if TOKEN:
            query = parse_qs(parsed.query)
            key = (query.get("key") or [""])[0]
            if key != TOKEN:
                _json_response(self, 401, {"ok": False, "error": "unauthorized"})
                return

        length_header = self.headers.get("Content-Length", "0")
        try:
            length = int(length_header)
        except ValueError:
            length = 0

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
        # Reduce ruido en consola; comenta esta función si quieres logs HTTP.
        return


def main():
    server = ThreadingHTTPServer((HOST, PORT), FeedbackHandler)
    print(f"Feedback server escuchando en http://{HOST}:{PORT}/feedback")
    if TOKEN:
        print("Token activo: se requiere ?key=TOKEN")
    else:
        print("Aviso: sin token; el endpoint acepta cualquier POST.")
    server.serve_forever()


if __name__ == "__main__":
    main()
