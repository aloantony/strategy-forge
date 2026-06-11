// api.js — acceso a la API del servidor (REST + WebSocket). Espejo JS del ApiClient.

async function request(method, path, { params, body } = {}) {
  let url = path;
  if (params) {
    const qs = new URLSearchParams(params).toString();
    if (qs) url += `?${qs}`;
  }
  let response;
  try {
    response = await fetch(url, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    throw new Error(`Sin conexión con el servidor (${err.message})`);
  }
  if (!response.ok) {
    let detail = response.statusText;
    try { detail = (await response.json()).detail ?? detail; } catch { /* no-json */ }
    throw new Error(`HTTP ${response.status}: ${detail}`);
  }
  return response.json();
}

export const apiGet = (path, params) => request("GET", path, { params });
export const apiPost = (path, body) => request("POST", path, { body });
export const apiPut = (path, body) => request("PUT", path, { body });
export const apiDelete = (path) => request("DELETE", path);

// Suscripción al stream de snapshots con reconexión (backoff simple).
// Devuelve una función para cancelar.
export function subscribeStream({ symbol = "", magic = 0, onSnapshot, onStatus }) {
  let ws = null;
  let closed = false;
  let retryMs = 1000;

  const connect = () => {
    if (closed) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws/stream?symbol=${encodeURIComponent(symbol)}&magic=${magic}`);
    ws.onopen = () => { retryMs = 1000; onStatus?.("conectado"); };
    ws.onmessage = (ev) => {
      try { onSnapshot(JSON.parse(ev.data)); } catch { /* mensaje no-json */ }
    };
    ws.onclose = () => {
      if (closed) return;
      onStatus?.("reconectando…");
      setTimeout(connect, retryMs);
      retryMs = Math.min(retryMs * 2, 15000);
    };
    ws.onerror = () => ws.close();
  };

  connect();
  return () => { closed = true; ws?.close(); };
}
