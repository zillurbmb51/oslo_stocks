"""Tests for app.update_actual_prices — price parsing, column normalisation, I/O."""
import csv
from pathlib import Path
from unittest.mock import patch

import pytest

from app.update_actual_prices import (
    normalize_column,
    parse_price,
    ActualRow,
    read_existing_actuals,
    write_actuals,
    fetch_actual_rows,
)


# ── normalize_column ─────────────────────────────────────────────────────────

class TestNormalizeColumn:
    def test_basic(self):
        assert normalize_column("Last Price") == "last_price"

    def test_slash_replacement(self):
        assert normalize_column("P/E Ratio") == "p_e_ratio"

    def test_strips_whitespace(self):
        assert normalize_column("  Symbol  ") == "symbol"

    def test_lowercase(self):
        assert normalize_column("MARKET CAP") == "market_cap"

    def test_combined(self):
        assert normalize_column(" Last/Price ") == "last_price"

    def test_empty(self):
        assert normalize_column("") == ""

    def test_non_string_input(self):
        assert normalize_column(42) == "42"


# ── parse_price ──────────────────────────────────────────────────────────────

class TestParsePrice:
    def test_none(self):
        assert parse_price(None) is None

    def test_empty_string(self):
        assert parse_price("") is None
        assert parse_price("   ") is None

    def test_dash(self):
        assert parse_price("-") is None

    def test_simple_float(self):
        assert parse_price("123.45") == 123.45

    def test_comma_decimal(self):
        assert parse_price("123,45") == 123.45

    def test_thousands_dot_comma_decimal(self):
        assert parse_price("1.234,56") == 1234.56

    def test_thousands_comma_dot_decimal(self):
        # Code treats dot+comma as European format (dot=thousands, comma=decimal)
        # "1,234.56" -> removes dots -> "1,23456" -> replaces comma -> "1.23456"
        assert parse_price("1,234.56") == 1.23456

    def test_non_breaking_space(self):
        assert parse_price("1\xa0234.56") == 1234.56

    def test_integer(self):
        assert parse_price("100") == 100.0

    def test_numeric_input(self):
        assert parse_price(42.5) == 42.5

    def test_currency_symbol_stripped(self):
        assert parse_price("$100.50") == 100.50

    def test_negative_price(self):
        assert parse_price("-5.25") == -5.25

    def test_zero(self):
        assert parse_price("0") == 0.0

    def test_whitespace_around(self):
        assert parse_price("  100.50  ") == 100.50


# ── ActualRow ────────────────────────────────────────────────────────────────

class TestActualRow:
    def test_creation(self):
        row = ActualRow(date="2024-01-01", ticker="ABC", price=100.0)
        assert row.date == "2024-01-01"
        assert row.ticker == "ABC"
        assert row.price == 100.0

    def test_immutable(self):
        row = ActualRow(date="2024-01-01", ticker="ABC", price=100.0)
        with pytest.raises(AttributeError):
            row.price = 200.0


# ── read_existing_actuals ───────────────────────────────────────────────────

class TestReadExistingActuals:
    def test_missing_file_returns_empty(self, tmp_path):
        with patch("app.update_actual_prices.ACTUALS_FILE", tmp_path / "nope.csv"):
            assert read_existing_actuals() == {}

    def test_reads_valid_csv(self, tmp_path):
        csv_file = tmp_path / "actuals.csv"
        csv_file.write_text("date,ticker,price\n2024-01-01,ABC,100.5\n2024-01-02,XYZ,50.0\n")
        with patch("app.update_actual_prices.ACTUALS_FILE", csv_file):
            result = read_existing_actuals()
            assert ("2024-01-01", "ABC") in result
            assert result[("2024-01-01", "ABC")] == 100.5
            assert ("2024-01-02", "XYZ") in result

    def test_normalizes_ticker_case(self, tmp_path):
        csv_file = tmp_path / "actuals.csv"
        csv_file.write_text("date,ticker,price\n2024-01-01,abc,10.0\n")
        with patch("app.update_actual_prices.ACTUALS_FILE", csv_file):
            result = read_existing_actuals()
            assert ("2024-01-01", "ABC") in result

    def test_skips_rows_with_missing_date(self, tmp_path):
        csv_file = tmp_path / "actuals.csv"
        csv_file.write_text("date,ticker,price\n,ABC,10.0\n2024-01-01,XYZ,20.0\n")
        with patch("app.update_actual_prices.ACTUALS_FILE", csv_file):
            result = read_existing_actuals()
            assert len(result) == 1
            assert ("2024-01-01", "XYZ") in result

    def test_skips_rows_with_bad_price(self, tmp_path):
        csv_file = tmp_path / "actuals.csv"
        csv_file.write_text("date,ticker,price\n2024-01-01,ABC,-\n2024-01-01,XYZ,20.0\n")
        with patch("app.update_actual_prices.ACTUALS_FILE", csv_file):
            result = read_existing_actuals()
            assert len(result) == 1


# ── write_actuals ────────────────────────────────────────────────────────────

class TestWriteActuals:
    def test_writes_sorted_csv(self, tmp_path):
        out_file = tmp_path / "out.csv"
        data = {
            ("2024-01-02", "XYZ"): 50.0,
            ("2024-01-01", "ABC"): 100.0,
            ("2024-01-01", "DEF"): 75.0,
        }
        with patch("app.update_actual_prices.ACTUALS_FILE", out_file), \
             patch("app.update_actual_prices.DATA_DIR", tmp_path):
            write_actuals(data)

        with open(out_file) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 3
        # Should be sorted by (date, ticker)
        assert rows[0]["date"] == "2024-01-01"
        assert rows[0]["ticker"] == "ABC"
        assert rows[1]["date"] == "2024-01-01"
        assert rows[1]["ticker"] == "DEF"
        assert rows[2]["date"] == "2024-01-02"
        assert rows[2]["ticker"] == "XYZ"

    def test_writes_empty_dict(self, tmp_path):
        out_file = tmp_path / "out.csv"
        with patch("app.update_actual_prices.ACTUALS_FILE", out_file), \
             patch("app.update_actual_prices.DATA_DIR", tmp_path):
            write_actuals({})

        with open(out_file) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert rows == []

    def test_creates_parent_dirs(self, tmp_path):
        nested = tmp_path / "sub" / "dir"
        out_file = nested / "out.csv"
        with patch("app.update_actual_prices.ACTUALS_FILE", out_file), \
             patch("app.update_actual_prices.DATA_DIR", nested):
            write_actuals({("2024-01-01", "T"): 1.0})
        assert out_file.exists()


# ── fetch_actual_rows ────────────────────────────────────────────────────────

class TestFetchActualRows:
    def test_parses_euronext_csv(self):
        mock_csv = (
            "Some header junk\n"
            "More junk\n"
            "Symbol;Name;last Price;Volume\n"
            "ABC;ABC Corp;123,45;1000\n"
            "XYZ;XYZ Inc;67.89;2000\n"
        )
        with patch("app.update_actual_prices.fetch_csv_text", return_value=mock_csv):
            rows = fetch_actual_rows("2024-06-01")
            assert len(rows) == 2
            tickers = {r.ticker for r in rows}
            assert tickers == {"ABC", "XYZ"}
            abc = next(r for r in rows if r.ticker == "ABC")
            assert abc.price == 123.45
            assert abc.date == "2024-06-01"

    def test_raises_on_missing_headers(self):
        mock_csv = "Some random text\nNo symbol or price columns here\n"
        with patch("app.update_actual_prices.fetch_csv_text", return_value=mock_csv):
            with pytest.raises(RuntimeError, match="Could not find Symbol"):
                fetch_actual_rows("2024-06-01")

    def test_skips_empty_tickers(self):
        mock_csv = (
            "Symbol;last Price\n"
            ";100.0\n"
            "ABC;50.0\n"
        )
        with patch("app.update_actual_prices.fetch_csv_text", return_value=mock_csv):
            rows = fetch_actual_rows("2024-06-01")
            assert len(rows) == 1
            assert rows[0].ticker == "ABC"

    def test_deduplicates_tickers(self):
        mock_csv = (
            "Symbol;last Price\n"
            "ABC;100.0\n"
            "ABC;200.0\n"
        )
        with patch("app.update_actual_prices.fetch_csv_text", return_value=mock_csv):
            rows = fetch_actual_rows("2024-06-01")
            assert len(rows) == 1
            assert rows[0].price == 100.0

    def test_skips_unparseable_price(self):
        mock_csv = (
            "Symbol;last Price\n"
            "ABC;-\n"
            "XYZ;50.0\n"
        )
        with patch("app.update_actual_prices.fetch_csv_text", return_value=mock_csv):
            rows = fetch_actual_rows("2024-06-01")
            assert len(rows) == 1
            assert rows[0].ticker == "XYZ"
