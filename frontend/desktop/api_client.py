# Trading Agent — https://github.com/aloantony/trading-agent
# Required Notice: Copyright 2026 aloantony (https://github.com/aloantony)
# Licensed under the PolyForm Noncommercial License 1.0.0 — see LICENSE, or
# <https://polyformproject.org/licenses/noncommercial/1.0.0>. Noncommercial use
# is free; commercial use, including production use, requires a written
# agreement with the copyright holder.

"""
frontend/desktop/api_client.py — Cliente de la API del servidor (REST + WebSocket).

Único punto de acceso del frontend al backend: la GUI no debe importar MT5 ni
módulos de backend/ directamente; todo pasa por aquí contra server/ (FastAPI).

REST  -> httpx (síncrono; las secciones de la GUI ya trabajan con callbacks/hilos).
WS    -> websockets.sync en un hilo de fondo con callback por snapshot.
"""

import json
import threading
from typing import Callable, Optional

import httpx
from websockets.sync.client import connect as ws_connect


class ApiClientError(RuntimeError):
    """Error de transporte o respuesta no-2xx de la API."""


class ApiClient:

    def __init__(self, base_url: str = "http://127.0.0.1:8000", timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout)
        self._stream_thread: Optional[threading.Thread] = None
        self._stream_stop = threading.Event()

    # ------------------------------------------------------------------
    # REST
    # ------------------------------------------------------------------

    def health(self) -> dict:
        return self._get("/api/health")

    def list_strategies(self, load_modules: bool = False) -> list:
        return self._get("/api/strategies", params={"load_modules": load_modules})

    def enable_strategy(self, key: str) -> dict:
        return self._post(f"/api/strategies/{key}/enable")

    def disable_strategy(self, key: str) -> dict:
        return self._post(f"/api/strategies/{key}/disable")

    def get_account(self) -> dict:
        return self._get("/api/account")

    def get_positions(self, symbol: str = "", magic: int = 0) -> dict:
        return self._get("/api/positions", params={"symbol": symbol, "magic": magic})

    def get_market_status(self, symbol: str = "") -> dict:
        return self._get("/api/market-status", params={"symbol": symbol})

    def get_candles(self, symbol: str = "", timeframe: str = "M1", start: str = "",
                    end: str = "", source: str = "mt5", limit: int = 5000) -> dict:
        return self._get("/api/candles", params={
            "symbol": symbol, "timeframe": timeframe, "start": start,
            "end": end, "source": source, "limit": limit,
        })

    def run_backtest(self, strategy_key: str, symbol: str, start_date: str,
                     end_date: str, initial_balance: float = 10_000.0,
                     data_source: str = "mt5") -> dict:
        return self._post("/api/backtest/run", json={
            "strategy_key": strategy_key, "symbol": symbol,
            "start_date": start_date, "end_date": end_date,
            "initial_balance": initial_balance, "data_source": data_source,
        })

    # ------------------------------------------------------------------
    # WebSocket (stream de snapshots)
    # ------------------------------------------------------------------

    def subscribe_stream(self, on_snapshot: Callable[[dict], None],
                         symbol: str = "", magic: int = 0,
                         on_error: Callable[[Exception], None] = None) -> None:
        """Lanza un hilo que recibe snapshots de /ws/stream y llama a on_snapshot."""
        self.unsubscribe_stream()
        self._stream_stop.clear()
        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        url = f"{ws_url}/ws/stream?symbol={symbol}&magic={magic}"

        def _run():
            try:
                with ws_connect(url) as ws:
                    while not self._stream_stop.is_set():
                        on_snapshot(json.loads(ws.recv()))
            except Exception as exc:
                if not self._stream_stop.is_set() and on_error is not None:
                    on_error(exc)

        self._stream_thread = threading.Thread(target=_run, daemon=True,
                                               name="api-client-stream")
        self._stream_thread.start()

    def unsubscribe_stream(self) -> None:
        self._stream_stop.set()
        thread = self._stream_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)
        self._stream_thread = None

    def close(self) -> None:
        self.unsubscribe_stream()
        self._http.close()

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _get(self, path: str, params: dict = None):
        return self._request("GET", path, params=params)

    def _post(self, path: str, json: dict = None):
        return self._request("POST", path, json=json)

    def _request(self, method: str, path: str, **kwargs):
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ApiClientError(f"No se pudo contactar con el servidor: {exc}") from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            raise ApiClientError(f"HTTP {response.status_code}: {detail}")
        return response.json()
