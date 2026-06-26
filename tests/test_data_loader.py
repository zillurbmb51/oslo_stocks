"""Tests for app.data_loader — clean_comment, load helpers, and forecast loading."""
import textwrap
from io import StringIO
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from app.data_loader import (
    clean_comment,
    load_actual_prices,
    load_multi_run_forecasts,
    FORECAST_SOURCES,
)


# ── clean_comment ────────────────────────────────────────────────────────────

class TestCleanComment:
    def test_non_string_returns_empty(self):
        assert clean_comment(None) == ""
        assert clean_comment(123) == ""
        assert clean_comment([]) == ""

    def test_empty_string(self):
        assert clean_comment("") == ""

    def test_plain_text_passthrough(self):
        assert clean_comment("The stock is strong.") == "The stock is strong."

    def test_removes_leading_boilerplate(self):
        raw = "in plain text, without bullet points. The stock is strong."
        result = clean_comment(raw)
        assert "in plain text" not in result
        assert "The stock is strong." in result

    def test_removes_leading_boilerplate_case_insensitive(self):
        raw = "In Plain Text, Without Bullet Points. __ The outlook is bullish."
        result = clean_comment(raw)
        assert "In Plain Text" not in result
        assert "bullish" in result

    def test_removes_separator_underscores(self):
        raw = "Line one\n________\nLine two"
        result = clean_comment(raw)
        assert "________" not in result
        assert "Line one" in result
        assert "Line two" in result

    def test_removes_separator_dashes(self):
        raw = "Line one\n---\nLine two"
        result = clean_comment(raw)
        assert "---" not in result

    def test_removes_fenced_code_markers(self):
        raw = "```text\nSome commentary here\n```"
        result = clean_comment(raw)
        assert "```" not in result
        assert "Some commentary here" in result

    def test_removes_bare_text_plain_lines(self):
        raw = "text\nActual commentary."
        result = clean_comment(raw)
        assert result == "Actual commentary."

    def test_removes_here_is_commentary_boilerplate(self):
        raw = "Here is the commentary: The stock rose 5%."
        result = clean_comment(raw)
        assert "Here is the commentary" not in result
        assert "The stock rose 5%." in result

    def test_removes_here_is_your_commentary(self):
        raw = "Here is your commentary: Bullish trend."
        result = clean_comment(raw)
        assert "Here is your commentary" not in result
        assert "Bullish trend." in result

    def test_truncates_at_note_prompt(self):
        raw = "Good outlook.\nNote: this is auto-generated."
        result = clean_comment(raw)
        assert "Good outlook." in result
        assert "Note:" not in result

    def test_truncates_at_please_prompt(self):
        raw = "Strong performance.\nPlease review the data."
        result = clean_comment(raw)
        assert "Strong performance." in result
        assert "Please review" not in result

    def test_truncates_at_thank_you(self):
        raw = "Bearish trend.\nThank you for your feedback."
        result = clean_comment(raw)
        assert "Bearish trend." in result
        assert "Thank you" not in result

    def test_truncates_at_end_of_commentary(self):
        raw = "Some insight.\n[End of commentary]"
        result = clean_comment(raw)
        assert "Some insight." in result
        assert "[End of commentary]" not in result

    def test_collapses_excessive_blank_lines(self):
        raw = "Line one\n\n\n\n\nLine two"
        result = clean_comment(raw)
        assert "\n\n\n" not in result
        assert "Line one" in result
        assert "Line two" in result

    def test_strips_leading_text_or_plain(self):
        raw = "text   Actual content here."
        result = clean_comment(raw)
        assert result == "Actual content here."

    def test_combined_cleanup(self):
        raw = textwrap.dedent("""\
            in plain text, without bullet points.
            ```text
            Here is the commentary: The stock is trending upward.
            ________
            The 6-month outlook is bullish.
            ---
            Note: This is not financial advice.
        """)
        result = clean_comment(raw)
        assert "The stock is trending upward." in result
        assert "The 6-month outlook is bullish." in result
        assert "```" not in result
        assert "________" not in result
        assert "---" not in result
        assert "Note:" not in result

    def test_preserves_empty_lines_in_middle(self):
        raw = "Paragraph one.\n\nParagraph two."
        result = clean_comment(raw)
        assert "Paragraph one.\n\nParagraph two." == result


# ── load_actual_prices ───────────────────────────────────────────────────────

class TestLoadActualPrices:
    def test_missing_file_returns_empty(self, tmp_path):
        with patch("app.data_loader.ACTUALS_FILE", tmp_path / "nonexistent.csv"):
            result = load_actual_prices()
            assert result == {}

    def test_missing_columns_returns_empty(self, tmp_path):
        csv_file = tmp_path / "actuals.csv"
        csv_file.write_text("col_a,col_b\n1,2\n")
        with patch("app.data_loader.ACTUALS_FILE", csv_file):
            result = load_actual_prices()
            assert result == {}

    def test_loads_valid_csv(self, tmp_path):
        csv_file = tmp_path / "actuals.csv"
        csv_file.write_text(
            "date,ticker,price\n"
            "2024-01-01,ABC,100.5\n"
            "2024-01-02,ABC,101.0\n"
            "2024-01-01,XYZ,50.0\n"
        )
        with patch("app.data_loader.ACTUALS_FILE", csv_file):
            result = load_actual_prices()
            assert "ABC" in result
            assert "XYZ" in result
            assert result["ABC"]["dates"] == ["2024-01-01", "2024-01-02"]
            assert result["ABC"]["prices"] == [100.5, 101.0]
            assert result["XYZ"]["dates"] == ["2024-01-01"]
            assert result["XYZ"]["prices"] == [50.0]

    def test_normalizes_ticker_case(self, tmp_path):
        csv_file = tmp_path / "actuals.csv"
        csv_file.write_text("date,ticker,price\n2024-01-01,abc,10.0\n")
        with patch("app.data_loader.ACTUALS_FILE", csv_file):
            result = load_actual_prices()
            assert "ABC" in result

    def test_drops_na_rows(self, tmp_path):
        csv_file = tmp_path / "actuals.csv"
        csv_file.write_text(
            "date,ticker,price\n"
            "2024-01-01,ABC,100.0\n"
            ",ABC,50.0\n"
            "2024-01-02,ABC,\n"
        )
        with patch("app.data_loader.ACTUALS_FILE", csv_file):
            result = load_actual_prices()
            assert len(result["ABC"]["dates"]) == 1


# ── load_multi_run_forecasts ─────────────────────────────────────────────────

class TestLoadMultiRunForecasts:
    def test_loads_single_source(self, tmp_path):
        tsv_file = tmp_path / "test_forecast.tsv"
        tsv_file.write_text(
            "ticker\tprice_24h\tprice_1w\tcomment\n"
            "ABC\t100.0\t105.0\tsome comment\n"
            "XYZ\t50.0\t52.0\tanother comment\n"
        )
        mock_sources = [
            {"label": "TestModel", "path": tsv_file, "sep": "\t"},
        ]
        with patch("app.data_loader.FORECAST_SOURCES", mock_sources):
            result = load_multi_run_forecasts()
            assert "ABC" in result
            assert "XYZ" in result
            assert len(result["ABC"]) == 1
            run = result["ABC"][0]
            assert run["run_label"] == "TestModel"
            assert run["horizons"] == ["24h", "1w"]
            assert run["values"] == [100.0, 105.0]

    def test_skips_file_without_price_columns(self, tmp_path):
        tsv_file = tmp_path / "no_prices.tsv"
        tsv_file.write_text("ticker\tcomment\nABC\tsome text\n")
        mock_sources = [
            {"label": "BadModel", "path": tsv_file, "sep": "\t"},
        ]
        with patch("app.data_loader.FORECAST_SOURCES", mock_sources):
            result = load_multi_run_forecasts()
            assert result == {}

    def test_skips_na_values(self, tmp_path):
        tsv_file = tmp_path / "with_na.tsv"
        tsv_file.write_text(
            "ticker\tprice_24h\tprice_1w\n"
            "ABC\t100.0\t\n"
        )
        mock_sources = [
            {"label": "TestModel", "path": tsv_file, "sep": "\t"},
        ]
        with patch("app.data_loader.FORECAST_SOURCES", mock_sources):
            result = load_multi_run_forecasts()
            run = result["ABC"][0]
            assert run["horizons"] == ["24h"]
            assert run["values"] == [100.0]

    def test_multiple_sources_sorted_by_index(self, tmp_path):
        tsv1 = tmp_path / "model1.tsv"
        tsv2 = tmp_path / "model2.tsv"
        tsv1.write_text("ticker\tprice_24h\nABC\t100.0\n")
        tsv2.write_text("ticker\tprice_24h\nABC\t200.0\n")
        mock_sources = [
            {"label": "Model1", "path": tsv1, "sep": "\t"},
            {"label": "Model2", "path": tsv2, "sep": "\t"},
        ]
        with patch("app.data_loader.FORECAST_SOURCES", mock_sources):
            result = load_multi_run_forecasts()
            assert len(result["ABC"]) == 2
            assert result["ABC"][0]["run_label"] == "Model1"
            assert result["ABC"][1]["run_label"] == "Model2"

    def test_empty_ticker_skipped(self, tmp_path):
        tsv_file = tmp_path / "empty_ticker.tsv"
        tsv_file.write_text("ticker\tprice_24h\n\t100.0\nABC\t50.0\n")
        mock_sources = [
            {"label": "M", "path": tsv_file, "sep": "\t"},
        ]
        with patch("app.data_loader.FORECAST_SOURCES", mock_sources):
            result = load_multi_run_forecasts()
            assert "" not in result
            assert "ABC" in result
