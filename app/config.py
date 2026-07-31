"""Shared configuration for the app package."""
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
HISTORY_FILE = DATA_DIR / "oslo_stock_exchange_all_companies.xlsx"
ACTUALS_FILE = DATA_DIR / "oslo_actual_prices.csv"
RATIONALES_FILE = DATA_DIR / "ticker_rationales_osl_parallel.csv"


def normalize_ticker(raw: str) -> str:
    """Trim whitespace and uppercase a raw ticker string."""
    return str(raw).strip().upper()
