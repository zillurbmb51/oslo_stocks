"""Tests for app.models — Pydantic model validation and serialization."""
import pytest
from pydantic import ValidationError

from app.models import (
    RunSeries,
    ForecastMultiRun,
    CommentaryBlock,
    CommentaryResponse,
    TickerList,
    ActualSeries,
    TickerMetric,
    TickerMetricList,
)


class TestRunSeries:
    def test_valid_creation(self):
        rs = RunSeries(run_index=1, run_label="FinGPT1", horizons=["24h", "1w"], values=[100.0, 105.0])
        assert rs.run_index == 1
        assert rs.run_label == "FinGPT1"
        assert rs.horizons == ["24h", "1w"]
        assert rs.values == [100.0, 105.0]

    def test_empty_lists(self):
        rs = RunSeries(run_index=0, run_label="", horizons=[], values=[])
        assert rs.horizons == []
        assert rs.values == []

    def test_missing_required_field(self):
        with pytest.raises(ValidationError):
            RunSeries(run_index=1, run_label="X", horizons=["24h"])

    def test_wrong_type_run_index(self):
        with pytest.raises(ValidationError):
            RunSeries(run_index="abc", run_label="X", horizons=[], values=[])


class TestForecastMultiRun:
    def test_valid_creation(self):
        run = RunSeries(run_index=1, run_label="M1", horizons=["24h"], values=[100.0])
        fm = ForecastMultiRun(ticker="ABC", runs=[run])
        assert fm.ticker == "ABC"
        assert len(fm.runs) == 1

    def test_empty_runs(self):
        fm = ForecastMultiRun(ticker="ABC", runs=[])
        assert fm.runs == []

    def test_missing_ticker(self):
        with pytest.raises(ValidationError):
            ForecastMultiRun(runs=[])


class TestCommentaryBlock:
    def test_valid(self):
        cb = CommentaryBlock(source="FinGPT", commentary="Bullish outlook.")
        assert cb.source == "FinGPT"
        assert cb.commentary == "Bullish outlook."

    def test_missing_fields(self):
        with pytest.raises(ValidationError):
            CommentaryBlock(source="FinGPT")


class TestCommentaryResponse:
    def test_valid(self):
        block = CommentaryBlock(source="FinGPT", commentary="text")
        cr = CommentaryResponse(ticker="ABC", commentaries=[block])
        assert cr.ticker == "ABC"
        assert len(cr.commentaries) == 1


class TestTickerList:
    def test_valid(self):
        tl = TickerList(tickers=["ABC", "XYZ"])
        assert tl.tickers == ["ABC", "XYZ"]

    def test_empty(self):
        tl = TickerList(tickers=[])
        assert tl.tickers == []


class TestActualSeries:
    def test_valid(self):
        a = ActualSeries(ticker="ABC", dates=["2024-01-01"], prices=[100.0])
        assert a.ticker == "ABC"
        assert a.dates == ["2024-01-01"]
        assert a.prices == [100.0]


class TestTickerMetric:
    def test_valid(self):
        tm = TickerMetric(ticker="ABC", prediction_ratio=0.85)
        assert tm.ticker == "ABC"
        assert tm.prediction_ratio == 0.85

    def test_zero_ratio(self):
        tm = TickerMetric(ticker="ABC", prediction_ratio=0.0)
        assert tm.prediction_ratio == 0.0


class TestTickerMetricList:
    def test_valid(self):
        m1 = TickerMetric(ticker="ABC", prediction_ratio=0.8)
        m2 = TickerMetric(ticker="XYZ", prediction_ratio=0.9)
        tml = TickerMetricList(tickers=[m1, m2])
        assert len(tml.tickers) == 2

    def test_serialization_roundtrip(self):
        m = TickerMetric(ticker="ABC", prediction_ratio=0.85)
        tml = TickerMetricList(tickers=[m])
        data = tml.model_dump()
        assert data == {"tickers": [{"ticker": "ABC", "prediction_ratio": 0.85}]}
        restored = TickerMetricList(**data)
        assert restored == tml
