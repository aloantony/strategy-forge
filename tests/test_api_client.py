"""
tests/test_api_client.py — End-to-end del ApiClient del frontend contra un
servidor uvicorn real (broker paper, puerto efímero). No requiere MT5.
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import uvicorn

from frontend.desktop.api_client import ApiClient, ApiClientError
from server.app import create_app


def _start_server() -> tuple[uvicorn.Server, threading.Thread, int]:
    config = uvicorn.Config(create_app(broker_name="paper"), host="127.0.0.1",
                            port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("uvicorn no arrancó a tiempo")
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    return server, thread, port


def test_api_client_end_to_end():
    server, thread, port = _start_server()
    client = ApiClient(f"http://127.0.0.1:{port}")
    try:
        # REST
        assert client.health()["broker"] == "PaperBrokerAdapter"
        strategies = client.list_strategies()
        assert any(s["key"] == "strategy_primera_estrategia" for s in strategies)
        assert client.get_account()["balance"] > 0
        assert client.get_positions(symbol="TEST", magic=1)["positions"] == []
        assert client.get_market_status(symbol="TEST")["open"] is True

        # Errores legibles
        try:
            client.enable_strategy("no_existe")
            assert False, "deberia lanzar ApiClientError"
        except ApiClientError as exc:
            assert "404" in str(exc)

        # WebSocket: recibir al menos un snapshot
        received = []
        done = threading.Event()

        def on_snapshot(msg):
            received.append(msg)
            done.set()

        client.subscribe_stream(on_snapshot, symbol="TEST", magic=1)
        assert done.wait(timeout=10), "no llegó ningún snapshot por WS"
        client.unsubscribe_stream()
        assert received[0]["type"] == "snapshot"
        assert received[0]["account"]["balance"] > 0
    finally:
        client.close()
        server.should_exit = True
        thread.join(timeout=10)
    print("PASS test_api_client_end_to_end")


if __name__ == "__main__":
    test_api_client_end_to_end()
    print("\nAll tests passed.")
