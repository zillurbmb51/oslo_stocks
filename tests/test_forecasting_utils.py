"""Tests for forecasting.utils — log_trend_extrapolate, generate_comment, HORIZON_MAP."""
import math

import numpy as np
import pytest

from forecasting.utils import (
    HORIZON_MAP,
    MIN_HISTORY_ROWS,
    log_trend_extrapolate,
    generate_comment,
)


# ── HORIZON_MAP / constants ──────────────────────────────────────────────────

class TestConstants:
    def test_horizon_map_has_14_entries(self):
        assert len(HORIZON_MAP) == 14

    def test_horizon_map_ascending_business_days(self):
        bdays = [bdays for _, bdays in HORIZON_MAP]
        assert bdays == sorted(bdays)

    def test_horizon_map_starts_at_1(self):
        assert HORIZON_MAP[0] == ("price_24h", 1)

    def test_horizon_map_ends_at_1260(self):
        assert HORIZON_MAP[-1] == ("price_5y", 1260)

    def test_min_history_rows(self):
        assert MIN_HISTORY_ROWS == 60


# ── log_trend_extrapolate ────────────────────────────────────────────────────

class TestLogTrendExtrapolate:
    def test_same_horizon_returns_anchor(self):
        result = log_trend_extrapolate(100.0, 110.0, 252, 252)
        assert abs(result - 110.0) < 0.01

    def test_zero_horizon_returns_last_price(self):
        result = log_trend_extrapolate(100.0, 110.0, 252, 0)
        assert abs(result - 100.0) < 0.01

    def test_double_horizon_extrapolates(self):
        result = log_trend_extrapolate(100.0, 110.0, 252, 504)
        # 10% growth over 252 days -> ~21% over 504 days (log-linear)
        expected = 100.0 * (110.0 / 100.0) ** (504.0 / 252.0)
        assert abs(result - expected) < 0.01

    def test_declining_price(self):
        result = log_trend_extrapolate(100.0, 90.0, 252, 504)
        # Should be less than 90
        assert result < 90.0

    def test_last_price_zero_returns_last_price(self):
        result = log_trend_extrapolate(0.0, 110.0, 252, 504)
        assert result == 0.0

    def test_anchor_bdays_zero_returns_last_price(self):
        result = log_trend_extrapolate(100.0, 110.0, 0, 504)
        assert result == 100.0

    def test_negative_last_price_returns_last_price(self):
        result = log_trend_extrapolate(-5.0, 110.0, 252, 504)
        assert result == -5.0

    def test_very_small_anchor_price(self):
        result = log_trend_extrapolate(100.0, 0.0, 252, 504)
        # anchor_price clamped to 1e-8 -> result should be >= 0
        assert result >= 0

    def test_result_never_negative(self):
        result = log_trend_extrapolate(100.0, 0.001, 252, 1260)
        assert result >= 0

    def test_short_extrapolation(self):
        result = log_trend_extrapolate(100.0, 105.0, 10, 5)
        # Half the horizon -> sqrt of ratio
        expected = 100.0 * (105.0 / 100.0) ** 0.5
        assert abs(result - expected) < 0.01


# ── generate_comment ─────────────────────────────────────────────────────────

class TestGenerateComment:
    def test_all_horizons_present(self):
        forecasts = {
            "price_1m": 110.0,
            "price_6m": 120.0,
            "price_1y": 130.0,
            "price_5y": 200.0,
        }
        result = generate_comment("ABC", 100.0, forecasts)
        assert "ABC" in result
        assert "short-term" in result.lower() or "1-month" in result.lower()
        assert "6 months" in result.lower()
        assert "1-year" in result.lower()
        assert "5-year" in result.lower()

    def test_no_forecasts(self):
        result = generate_comment("ABC", 100.0, {})
        assert "Insufficient data" in result
        assert "ABC" in result

    def test_only_1m_forecast(self):
        forecasts = {"price_1m": 110.0}
        result = generate_comment("ABC", 100.0, forecasts)
        assert "1-month" in result.lower() or "short-term" in result.lower()
        assert "6 months" not in result.lower()

    def test_strongly_bullish_direction(self):
        forecasts = {"price_1m": 115.0}
        result = generate_comment("ABC", 100.0, forecasts)
        assert "strongly bullish" in result

    def test_bullish_direction(self):
        forecasts = {"price_1m": 105.0}
        result = generate_comment("ABC", 100.0, forecasts)
        assert "bullish" in result

    def test_mildly_bullish_direction(self):
        forecasts = {"price_1m": 101.0}
        result = generate_comment("ABC", 100.0, forecasts)
        assert "mildly bullish" in result

    def test_strongly_bearish_direction(self):
        forecasts = {"price_1m": 85.0}
        result = generate_comment("ABC", 100.0, forecasts)
        assert "strongly bearish" in result

    def test_bearish_direction(self):
        forecasts = {"price_1m": 95.0}
        result = generate_comment("ABC", 100.0, forecasts)
        assert "bearish" in result

    def test_mildly_bearish_direction(self):
        forecasts = {"price_1m": 99.0}
        result = generate_comment("ABC", 100.0, forecasts)
        assert "mildly bearish" in result

    def test_sideways_direction(self):
        forecasts = {"price_1m": 100.25}
        result = generate_comment("ABC", 100.0, forecasts)
        assert "sideways" in result

    def test_zero_last_price(self):
        forecasts = {"price_1m": 10.0}
        result = generate_comment("ABC", 0.0, forecasts)
        # pct returns None when last_price is falsy -> no parts added
        assert "Insufficient data" in result

    def test_6m_includes_target_price(self):
        forecasts = {"price_6m": 120.0}
        result = generate_comment("ABC", 100.0, forecasts)
        assert "120.00" in result

    def test_1y_includes_target_price(self):
        forecasts = {"price_1y": 130.0}
        result = generate_comment("ABC", 100.0, forecasts)
        assert "130.00" in result

    def test_5y_includes_cumulative(self):
        forecasts = {"price_5y": 200.0}
        result = generate_comment("ABC", 100.0, forecasts)
        assert "200.00" in result
        assert "cumulative" in result.lower()

    def test_percentage_formatting(self):
        forecasts = {"price_1m": 110.0}
        result = generate_comment("ABC", 100.0, forecasts)
        assert "+10.0%" in result
