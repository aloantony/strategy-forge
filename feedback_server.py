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
    # Para peques: decidimos en que "puerta" (puerto) va a escuchar el servidor.
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
    # Para peques: convierte texto de variables de entorno en True/False.
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on", "si", "sí")


def _parse_allowed_ip_networks(raw: str):
    # Para peques: transforma "1.2.3.4,10.0.0.0/24" en reglas de red válidas.
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
    # Para peques: empaquetamos la respuesta en JSON y la devolvemos al cliente.
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status_code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _html_response(handler, status_code: int, html: str):
    # Para peques: enviamos una pagina web bonita para abrir en navegador.
    body = html.encode("utf-8")
    handler.send_response(status_code)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _get_public_base_url(handler) -> str:
    # Para peques: intentamos adivinar la URL publica (util en Koyeb con proxy).
    host = (
        (handler.headers.get("X-Forwarded-Host") or "").strip()
        or (handler.headers.get("Host") or "").strip()
    )
    if not host:
        host = f"{HOST}:{PORT}"
    forwarded_proto = (handler.headers.get("X-Forwarded-Proto") or "").strip()
    if forwarded_proto:
        proto = forwarded_proto
    else:
        host_only = host.split(":", 1)[0].lower()
        if host_only in ("127.0.0.1", "localhost", "0.0.0.0"):
            proto = "http"
        else:
            proto = "https"
    return f"{proto}://{host}"


def _build_strategy_guide_html(handler) -> str:
    # Para peques: construimos la pagina de guia para crear estrategias.
    base_url = _get_public_base_url(handler)
    return f"""<!doctype html>
<html lang="es">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Trading Agent · Guía de Estrategias</title>
    <style>
        :root {{
            --bg: #f4f5ef;
            --bg-accent: #fef8ee;
            --ink: #1f232b;
            --muted: #5c6573;
            --card: rgba(255, 255, 255, 0.82);
            --line: rgba(36, 40, 49, 0.13);
            --primary: #d9480f;
            --primary-soft: #ffe8d6;
            --secondary: #0f766e;
            --secondary-soft: #d9fbf7;
            --ok: #16a34a;
            --warn: #ca8a04;
            --radius: 18px;
            --shadow: 0 14px 30px rgba(25, 32, 45, 0.11);
            --mono: "IBM Plex Mono", "Consolas", "Courier New", monospace;
            --ui: "Sora", "Avenir Next", "Segoe UI", sans-serif;
        }}
        * {{
            box-sizing: border-box;
        }}
        body {{
            margin: 0;
            font-family: var(--ui);
            color: var(--ink);
            background:
                radial-gradient(1100px 580px at 8% -18%, rgba(249, 115, 22, 0.19), transparent 60%),
                radial-gradient(820px 420px at 96% -14%, rgba(20, 184, 166, 0.2), transparent 55%),
                linear-gradient(180deg, var(--bg-accent), var(--bg));
            min-height: 100vh;
            line-height: 1.45;
        }}
        .wrap {{
            width: min(1140px, calc(100% - 30px));
            margin: 24px auto 44px auto;
            position: relative;
        }}
        .hero {{
            border: 1px solid var(--line);
            border-radius: calc(var(--radius) + 8px);
            background:
                linear-gradient(120deg, rgba(255, 245, 236, 0.92), rgba(238, 251, 249, 0.92)),
                repeating-linear-gradient(
                    35deg,
                    rgba(255, 255, 255, 0.42),
                    rgba(255, 255, 255, 0.42) 12px,
                    rgba(255, 255, 255, 0.08) 12px,
                    rgba(255, 255, 255, 0.08) 24px
                );
            box-shadow: var(--shadow);
            padding: 28px 26px 24px 26px;
            animation: rise 0.55s ease both;
        }}
        .pill {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            border-radius: 999px;
            padding: 6px 11px;
            font-size: 11px;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            border: 1px solid rgba(217, 72, 15, 0.28);
            background: rgba(255, 237, 221, 0.9);
            color: #8f3412;
            font-weight: 700;
        }}
        h1 {{
            margin: 12px 0 9px 0;
            font-size: clamp(26px, 4.2vw, 42px);
            line-height: 1.08;
            letter-spacing: -0.02em;
        }}
        .hero p {{
            margin: 0;
            max-width: 760px;
            color: var(--muted);
            font-size: clamp(14px, 1.95vw, 17px);
        }}
        .chips {{
            display: flex;
            flex-wrap: wrap;
            gap: 9px;
            margin-top: 16px;
        }}
        .chip {{
            border: 1px solid var(--line);
            border-radius: 999px;
            padding: 6px 11px;
            background: rgba(255, 255, 255, 0.75);
            font-size: 12px;
            color: #3f4652;
            font-weight: 600;
        }}
        .grid {{
            margin-top: 16px;
            display: grid;
            grid-template-columns: 1.2fr 1fr;
            gap: 14px;
        }}
        .card {{
            background: var(--card);
            border: 1px solid var(--line);
            border-radius: var(--radius);
            box-shadow: var(--shadow);
            padding: 18px;
            backdrop-filter: blur(5px);
            animation: rise 0.55s ease both;
        }}
        .card h2 {{
            margin: 0 0 10px 0;
            font-size: 17px;
            letter-spacing: -0.01em;
        }}
        .card p {{
            margin: 0;
            color: var(--muted);
            font-size: 14px;
        }}
        .timeline {{
            margin-top: 12px;
            display: grid;
            gap: 8px;
        }}
        .step {{
            display: grid;
            grid-template-columns: 28px 1fr;
            gap: 9px;
            align-items: start;
            padding: 10px;
            border-radius: 12px;
            border: 1px solid var(--line);
            background: rgba(255, 255, 255, 0.72);
        }}
        .num {{
            width: 28px;
            height: 28px;
            border-radius: 9px;
            background: var(--primary-soft);
            color: #9f3a10;
            font-weight: 700;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 12px;
        }}
        .step strong {{
            display: block;
            font-size: 13px;
            margin-bottom: 2px;
        }}
        .step span {{
            font-size: 12px;
            color: var(--muted);
        }}
        .api-list {{
            margin: 0;
            padding: 0;
            list-style: none;
            display: grid;
            gap: 8px;
        }}
        .api-list li {{
            border: 1px solid var(--line);
            border-radius: 12px;
            background: rgba(255, 255, 255, 0.74);
            padding: 10px 11px;
        }}
        .api-list code {{
            font-family: var(--mono);
            font-size: 12px;
            color: #113246;
            background: rgba(20, 184, 166, 0.12);
            border-radius: 6px;
            padding: 2px 5px;
        }}
        .badge {{
            display: inline-block;
            margin-left: 7px;
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 0.07em;
            border-radius: 999px;
            padding: 3px 7px;
            border: 1px solid transparent;
        }}
        .req {{
            background: rgba(22, 163, 74, 0.16);
            border-color: rgba(22, 163, 74, 0.3);
            color: #176f38;
        }}
        .opt {{
            background: rgba(202, 138, 4, 0.16);
            border-color: rgba(202, 138, 4, 0.3);
            color: #815b00;
        }}
        .subgrid {{
            margin-top: 14px;
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 14px;
        }}
        .code-box {{
            border-radius: 14px;
            border: 1px solid rgba(15, 118, 110, 0.24);
            background: linear-gradient(180deg, #0f1720, #101924);
            color: #d8e2ec;
            padding: 14px;
            overflow: auto;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06);
        }}
        .code-box pre {{
            margin: 0;
            font-size: 12px;
            line-height: 1.48;
            font-family: var(--mono);
        }}
        .feature-grid {{
            margin-top: 10px;
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 10px;
        }}
        .feature {{
            border: 1px solid var(--line);
            border-radius: 12px;
            padding: 11px;
            background: rgba(255, 255, 255, 0.74);
        }}
        .feature h3 {{
            margin: 0 0 4px 0;
            font-size: 13px;
        }}
        .feature p {{
            margin: 0;
            font-size: 12px;
            color: var(--muted);
        }}
        .koyeb {{
            margin-top: 14px;
            padding: 14px;
            border-radius: 14px;
            border: 1px solid rgba(217, 72, 15, 0.22);
            background: linear-gradient(120deg, rgba(255, 234, 217, 0.66), rgba(224, 254, 251, 0.66));
            display: grid;
            gap: 8px;
        }}
        .koyeb strong {{
            font-size: 14px;
        }}
        .koyeb code {{
            display: block;
            width: 100%;
            overflow-wrap: anywhere;
            border: 1px solid rgba(31, 35, 43, 0.18);
            border-radius: 9px;
            background: rgba(255, 255, 255, 0.75);
            padding: 8px 9px;
            font-size: 12px;
            font-family: var(--mono);
        }}
        .note {{
            margin-top: 14px;
            font-size: 12px;
            color: var(--muted);
        }}
        footer {{
            margin-top: 16px;
            border-top: 1px solid var(--line);
            padding-top: 12px;
            color: var(--muted);
            font-size: 12px;
            text-align: center;
        }}
        a {{
            color: #9b3412;
            text-decoration: none;
            border-bottom: 1px solid rgba(155, 52, 18, 0.35);
        }}
        a:hover {{
            border-bottom-color: rgba(155, 52, 18, 0.8);
        }}
        @keyframes rise {{
            from {{
                opacity: 0;
                transform: translateY(12px);
            }}
            to {{
                opacity: 1;
                transform: translateY(0);
            }}
        }}
        @media (max-width: 960px) {{
            .grid {{
                grid-template-columns: 1fr;
            }}
            .subgrid {{
                grid-template-columns: 1fr;
            }}
            .feature-grid {{
                grid-template-columns: 1fr 1fr;
            }}
        }}
        @media (max-width: 620px) {{
            .wrap {{
                width: calc(100% - 18px);
                margin-top: 12px;
            }}
            .hero {{
                padding: 18px;
            }}
            .feature-grid {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body>
    <main class="wrap">
        <section class="hero">
            <span class="pill">Trading Agent · Strategy Guide</span>
            <h1>Desarrolla estrategias claras, robustas y listas para producción.</h1>
            <p>
                Esta URL es tu centro de referencia para crear, cargar y operar estrategias en el bot:
                API mínima, funciones avanzadas, flujo de trabajo y ejemplos listos para copiar.
            </p>
            <div class="chips">
                <span class="chip">API mínima validada por la GUI</span>
                <span class="chip">Ejemplos M1 con señales reales</span>
                <span class="chip">Data Window personalizado</span>
                <span class="chip">Integración con panel de estrategias</span>
            </div>
        </section>

        <section class="grid">
            <article class="card">
                <h2>Flujo recomendado</h2>
                <p>Este es el orden más simple para tener una estrategia corriendo en minutos:</p>
                <div class="timeline">
                    <div class="step">
                        <div class="num">1</div>
                        <div>
                            <strong>Crea el módulo en <code>strategies/</code></strong>
                            <span>Ejemplo: <code>strategies/mi_estrategia.py</code></span>
                        </div>
                    </div>
                    <div class="step">
                        <div class="num">2</div>
                        <div>
                            <strong>Implementa <code>get_last_signal(df, verbose=False)</code></strong>
                            <span>Debe retornar: <code>buy</code>, <code>sell</code> o <code>none</code>.</span>
                        </div>
                    </div>
                    <div class="step">
                        <div class="num">3</div>
                        <div>
                            <strong>Añade <code>TIMEFRAME</code> y cálculo de columnas</strong>
                            <span>Usa <code>prepare_dataframe</code> o <code>compute_signals</code>.</span>
                        </div>
                    </div>
                    <div class="step">
                        <div class="num">4</div>
                        <div>
                            <strong>Carga en GUI y activa la estrategia</strong>
                            <span>Pestaña Estrategias -> Añadir estrategia -> Iniciar motor.</span>
                        </div>
                    </div>
                </div>
            </article>

            <article class="card">
                <h2>Checklist de compatibilidad</h2>
                <ul class="api-list">
                    <li><code>get_last_signal(df, verbose=False)</code> <span class="badge req">Requerido</span></li>
                    <li><code>prepare_dataframe(df)</code> o <code>compute_signals(df, enable_signals)</code> <span class="badge req">Requerido</span></li>
                    <li><code>TIMEFRAME = "M1"</code> o <code>get_timeframe()</code> <span class="badge opt">Opcional</span></li>
                    <li><code>DATA_WINDOW_FIELDS = [...]</code> <span class="badge opt">Opcional</span></li>
                    <li><code>MAGIC_NUMBER = 123456</code> <span class="badge opt">Opcional</span></li>
                </ul>
                <p class="note">
                    Si algo falla, la GUI mostrará automáticamente un overlay de diagnóstico con los pasos pendientes.
                </p>
            </article>
        </section>

        <section class="subgrid">
            <article class="card">
                <h2>Ejemplo 1 · Plantilla mínima</h2>
                <div class="code-box"><pre>import pandas as pd

TIMEFRAME = "M1"

def get_last_signal(df: pd.DataFrame, verbose: bool = False) -> str:
    if len(df) < 2:
        return "none"
    row = df.iloc[-2]  # vela cerrada
    if row["close"] > row["open"]:
        return "buy"
    if row["close"] < row["open"]:
        return "sell"
    return "none"</pre></div>
            </article>

            <article class="card">
                <h2>Ejemplo 2 · EMA Cross + Data Window</h2>
                <div class="code-box"><pre>TIMEFRAME = "M1"
EMA_FAST = 9
EMA_SLOW = 21

DATA_WINDOW_FIELDS = [
    {{"key": "ema_fast", "label": "EMA Fast", "format": "price", "section": "EMA"}},
    {{"key": "ema_slow", "label": "EMA Slow", "format": "price", "section": "EMA"}},
]

def prepare_dataframe(df):
    df = df.copy()
    df["ema_fast"] = df["close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=EMA_SLOW, adjust=False).mean()
    return df

def get_last_signal(df, verbose=False):
    if len(df) < 3:
        return "none"
    i = len(df) - 2
    p = i - 1
    if df.iloc[p]["ema_fast"] <= df.iloc[p]["ema_slow"] and df.iloc[i]["ema_fast"] > df.iloc[i]["ema_slow"]:
        return "buy"
    if df.iloc[p]["ema_fast"] >= df.iloc[p]["ema_slow"] and df.iloc[i]["ema_fast"] < df.iloc[i]["ema_slow"]:
        return "sell"
    return "none"</pre></div>
            </article>
        </section>

        <section class="card">
            <h2>Funcionalidades que ya soporta el programa</h2>
            <div class="feature-grid">
                <div class="feature">
                    <h3>Múltiples estrategias activas</h3>
                    <p>Activa/desactiva estrategias sin reiniciar el bot y ejecuta varias en paralelo.</p>
                </div>
                <div class="feature">
                    <h3>Timeframe por estrategia</h3>
                    <p>Cada módulo puede fijar su marco temporal y la GUI se adapta automáticamente.</p>
                </div>
                <div class="feature">
                    <h3>Strategy Data + Data Window</h3>
                    <p>Visualiza métricas propias con <code>DATA_WINDOW_FIELDS</code> y selector de estrategia.</p>
                </div>
                <div class="feature">
                    <h3>Carga desde GUI o drag-and-drop</h3>
                    <p>Añade módulos por nombre o arrastra archivos <code>.py</code> directamente.</p>
                </div>
                <div class="feature">
                    <h3>Magic number estable</h3>
                    <p>Se calcula automáticamente por estrategia o puedes fijarlo manualmente.</p>
                </div>
                <div class="feature">
                    <h3>Motor con feedback visual</h3>
                    <p>Estado del motor, checklist de API y errores de carga visibles en tiempo real.</p>
                </div>
            </div>
        </section>

        <section class="koyeb">
            <strong>URLs útiles en tu despliegue de Koyeb</strong>
            <code>Guía de estrategias: {base_url}/strategies/guide</code>
            <code>Webhook feedback (POST): {base_url}/feedback</code>
            <code>Listado feedback (GET): {base_url}/feedback/list</code>
        </section>

        <footer>
            Trading Agent · Guía viva de estrategias.
            Puedes abrir esta URL desde el overlay de "Estrategia incompleta" dentro de la GUI.
        </footer>
    </main>
</body>
</html>
"""


def _check_token(parsed) -> bool:
    # Para peques: comprobamos la llave secreta para evitar que cualquiera envie datos.
    if not TOKEN:
        return True
    query = parse_qs(parsed.query)
    key = (query.get("key") or [""])[0]
    return key == TOKEN


def _parse_limit(parsed, default=50, max_limit=200):
    # Para peques: leemos cuantas sugerencias pidio el usuario, con limites seguros.
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
    # Para peques: abrimos archivos de feedback y devolvemos lo mas nuevo primero.
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
    # Para peques: intentamos detectar la IP real del cliente (directa o via proxy).
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
    # Para peques: decide si este cliente puede leer /feedback/list.
    client_ip = _get_client_ip(handler)
    if client_ip is None:
        return False

    if LIST_ALLOWED_NETWORKS:
        return any(client_ip in network for network in LIST_ALLOWED_NETWORKS)

    if LIST_LOCAL_ONLY:
        return client_ip.is_loopback

    return True


class FeedbackHandler(BaseHTTPRequestHandler):
    # Para peques: esta clase atiende las peticiones que llegan por internet.
    def do_GET(self):
        # Para peques: esta funcion sirve para atender peticiones GET del servidor.
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/health"):
            _json_response(self, 200, {"ok": True})
            return
        if parsed.path in ("/strategies/guide", "/docs/strategies", "/guide"):
            _html_response(self, 200, _build_strategy_guide_html(self))
            return
        if parsed.path == "/feedback/list":
            # Esta ruta devuelve la lista de sugerencias guardadas.
            if not _is_feedback_list_client_allowed(self):
                _json_response(self, 403, {"ok": False, "error": "forbidden_client"})
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
        # Para peques: esta funcion sirve para atender peticiones POST del servidor.
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
        # Para peques: dejamos esto vacio para que la consola no se llene de mensajes HTTP.
        # Reduce ruido en consola; comenta esta función si quieres logs HTTP.
        return


def main():
    # Para peques: esta funcion sirve para arrancar todo el programa.
    # Creamos el servidor y lo dejamos escuchando sin parar.
    server = ThreadingHTTPServer((HOST, PORT), FeedbackHandler)
    print(f"Feedback server escuchando en http://{HOST}:{PORT}/feedback")
    print("Endpoints activos: GET /health, GET /strategies/guide, POST /feedback, GET /feedback/list")
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
