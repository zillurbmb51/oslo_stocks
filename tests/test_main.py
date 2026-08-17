"""Tests for app.main — compute_prediction_ratio and API endpoints."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app, compute_prediction_ratio


# ── compute_prediction_ratio ─────────────────────────────────────────────────

class TestComputePredictionRatio:
    def test_empty_runs(self):
        assert compute_prediction_ratio([]) == 0.0

    def test_single_run_single_value(self):
        runs = [{"values": [100.0]}]
        assert compute_prediction_ratio(runs) == 1.0

    def test_single_run_multiple_values(self):
        runs = [{"values": [50.0, 100.0]}]
        assert compute_prediction_ratio(runs) == 0.5

    def test_multiple_runs(self):
        runs = [
            {"values": [80.0, 100.0]},
            {"values": [60.0, 120.0]},
        ]
        # min=60, max=120 -> ratio=0.5
        assert compute_prediction_ratio(runs) == 0.5

    def test_max_value_zero(self):
        runs = [{"values": [0.0]}]
        assert compute_prediction_ratio(runs) == 0.0

    def test_non_numeric_values_ignored(self):
        runs = [{"values": [50.0, "bad", None, 100.0]}]
        assert compute_prediction_ratio(runs) == 0.5

    def test_missing_values_key(self):
        runs = [{"other": [1, 2]}]
        assert compute_prediction_ratio(runs) == 0.0

    def test_empty_values_list(self):
        runs = [{"values": []}]
        assert compute_prediction_ratio(runs) == 0.0

    def test_identical_values(self):
        runs = [{"values": [75.0, 75.0, 75.0]}]
        assert compute_prediction_ratio(runs) == 1.0

    def test_negative_values(self):
        runs = [{"values": [-10.0, -5.0, 10.0]}]
        # min=-10, max=10 -> ratio=-1.0
        assert compute_prediction_ratio(runs) == -1.0


# ── API endpoints ────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    """Create a TestClient with pre-loaded mock data (bypass startup loader)."""
    import app.main as main_module

    main_module.TICKER_TO_FORECAST = {
        "ABC": [
            {
                "run_index": 1,
                "run_label": "Model1",
                "horizons": ["24h", "1w"],
                "values": [100.0, 105.0],
            }
        ],
    }
    main_module.TICKER_TO_COMMENTARIES = {
        "ABC": {
            "FinGPT1": "Bullish outlook for ABC.",
            "Chronos": "Steady growth expected.",
        },
    }
    main_module.TICKER_TO_HISTORY = {
        "ABC": {
            "dates": ["2024-01-01", "2024-01-02"],
            "closes": [99.0, 100.0],
        },
    }
    main_module.TICKER_TO_ACTUAL = {
        "ABC": {
            "dates": ["2024-01-03"],
            "prices": [101.0],
        },
    }
    main_module.TICKER_TO_RATIO = {
        "ABC": compute_prediction_ratio(main_module.TICKER_TO_FORECAST["ABC"]),
    }
    return TestClient(app, raise_server_exceptions=True)


class TestRootEndpoint:
    def test_root(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "message" in resp.json()


class TestListTickers:
    def test_returns_intersection(self, client):
        resp = client.get("/api/tickers")
        assert resp.status_code == 200
        data = resp.json()
        assert "tickers" in data
        assert "ABC" in data["tickers"]

    def test_empty_when_no_overlap(self):
        import app.main as main_module
        main_module.TICKER_TO_FORECAST = {"ABC": []}
        main_module.TICKER_TO_COMMENTARIES = {"XYZ": {"FinGPT1": "text"}}
        c = TestClient(app, raise_server_exceptions=True)
        resp = c.get("/api/tickers")
        assert resp.json()["tickers"] == []


class TestTickerMetrics:
    def test_returns_metrics(self, client):
        resp = client.get("/api/ticker-metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "tickers" in data
        assert len(data["tickers"]) == 1
        assert data["tickers"][0]["ticker"] == "ABC"
        assert "prediction_ratio" in data["tickers"][0]


class TestGetForecast:
    def test_valid_ticker(self, client):
        resp = client.get("/api/forecast/ABC")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "ABC"
        assert len(data["runs"]) == 1
        assert data["runs"][0]["run_label"] == "Model1"

    def test_case_insensitive(self, client):
        resp = client.get("/api/forecast/abc")
        assert resp.status_code == 200
        assert resp.json()["ticker"] == "ABC"

    def test_missing_ticker(self, client):
        resp = client.get("/api/forecast/NONEXISTENT")
        assert resp.status_code == 404

    def test_whitespace_stripped(self, client):
        resp = client.get("/api/forecast/ ABC ")
        assert resp.status_code == 200


class TestGetCommentary:
    def test_valid_ticker(self, client):
        resp = client.get("/api/commentary/ABC")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "ABC"
        assert len(data["commentaries"]) == 2
        sources = [c["source"] for c in data["commentaries"]]
        assert "FinGPT" in sources
        assert "Chronos" in sources

    def test_missing_ticker(self, client):
        resp = client.get("/api/commentary/NONEXISTENT")
        assert resp.status_code == 404


class TestGetHistory:
    def test_valid_ticker(self, client):
        resp = client.get("/api/history/ABC")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "ABC"
        assert data["dates"] == ["2024-01-01", "2024-01-02"]
        assert data["closes"] == [99.0, 100.0]

    def test_missing_ticker(self, client):
        resp = client.get("/api/history/NONEXISTENT")
        assert resp.status_code == 404


class TestGetActual:
    def test_valid_ticker(self, client):
        # The endpoint re-reads from file each time; we mock load_actual_prices
        with patch("app.main.load_actual_prices", return_value={
            "ABC": {"dates": ["2024-01-03"], "prices": [101.0]}
        }):
            resp = client.get("/api/actual/ABC")
            assert resp.status_code == 200
            data = resp.json()
            assert data["ticker"] == "ABC"
            assert data["dates"] == ["2024-01-03"]
            assert data["prices"] == [101.0]

    def test_missing_ticker_returns_empty(self, client):
        with patch("app.main.load_actual_prices", return_value={}):
            resp = client.get("/api/actual/NONEXISTENT")
            assert resp.status_code == 200
            data = resp.json()
            assert data["dates"] == []
            assert data["prices"] == []
