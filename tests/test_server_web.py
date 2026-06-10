"""
tests/test_server_web.py — El servidor sirve el frontend web estático y /api/meta.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

from server.app import create_app


def _client() -> TestClient:
    return TestClient(create_app(broker_name="paper"))


def test_index_html_served():
    with _client() as client:
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "trading-agent" in r.text
        assert "/js/app.js" in r.text
    print("PASS test_index_html_served")


def test_static_assets_served():
    with _client() as client:
        for path, fragment in [
            ("/css/app.css", "--bg"),
            ("/js/app.js", "ChartView"),
            ("/js/api.js", "subscribeStream"),
            ("/vendor/lightweight-charts.js", "LightweightCharts"),
        ]:
            r = client.get(path)
            assert r.status_code == 200, path
            assert fragment in r.text, path
    print("PASS test_static_assets_served")


def test_meta_endpoint():
    with _client() as client:
        r = client.get("/api/meta")
        assert r.status_code == 200
        meta = r.json()
        assert meta["symbol_default"]
        assert "M1" in meta["timeframes"]
        assert meta["timeframe_minutes"]["H1"] == 60
        assert "mt5" in meta["data_sources"]
        assert isinstance(meta["dukascopy_available"], bool)
    print("PASS test_meta_endpoint")


def test_api_routes_take_priority_over_static():
    with _client() as client:
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
    print("PASS test_api_routes_take_priority_over_static")


if __name__ == "__main__":
    test_index_html_served()
    test_static_assets_served()
    test_meta_endpoint()
    test_api_routes_take_priority_over_static()
    print("\nAll tests passed.")
