"""Shared utilities for Oslo Stock Exchange forecast scripts."""
import logging
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
HISTORY_FILE = DATA_DIR / "oslo_stock_exchange_all_companies.xlsx"

# (output_column_name, business_days_ahead)
HORIZON_MAP: List[Tuple[str, int]] = [
    ("price_24h",    1),
    ("price_48h",    2),
    ("price_1w",     5),
    ("price_2w",    10),
    ("price_3w",    15),
    ("price_1m",    21),
    ("price_2m",    42),
    ("price_3m",    63),
    ("price_6m",   126),
    ("price_1y",   252),
    ("price_2y",   504),
    ("price_3y",   756),
    ("price_4y",  1008),
    ("price_5y",  1260),
]

MAX_HORIZON_BDAYS = 1260   # 5 years in business days
MIN_HISTORY_ROWS = 60      # minimum rows to attempt any forecast


def load_all_history(min_rows: int = MIN_HISTORY_ROWS) -> Dict[str, pd.DataFrame]:
    """
    Load all ticker history sheets from the Excel file.
    Returns {TICKER: DataFrame(Date, Close)} sorted by date ascending.
    Skips tickers with fewer than *min_rows* rows (default MIN_HISTORY_ROWS).
    """
    all_sheets = pd.read_excel(
        HISTORY_FILE, sheet_name=None, header=[0, 1], index_col=0
    )

    result: Dict[str, pd.DataFrame] = {}
    for sheet_name, df in all_sheets.items():
        ticker = str(sheet_name).strip().upper()

        close_col = None
        for col in df.columns:
            lvl0, _ = col
            if str(lvl0).strip().lower() == "close":
                close_col = col
                break

        if close_col is None:
            continue

        df_reset = df.reset_index()
        date_col = df_reset.columns[0]
        dh = df_reset[[date_col, close_col]].copy()
        dh.columns = ["Date", "Close"]
        dh = dh.dropna(subset=["Date", "Close"])
        dh["Date"] = pd.to_datetime(dh["Date"])
        dh["Close"] = (
            dh["Close"].astype(str)
            .str.replace(",", ".", regex=False)
            .astype(float)
        )
        dh = dh.sort_values("Date").reset_index(drop=True)

        if len(dh) < min_rows:
            continue

        result[ticker] = dh

    return result


def log_trend_extrapolate(last_price: float, anchor_price: float,
                           anchor_bdays: int, target_bdays: int) -> float:
    """
    Extrapolate a price at target_bdays using the log-linear trend implied
    by (last_price → anchor_price over anchor_bdays).
    """
    if last_price <= 0 or anchor_bdays <= 0:
        return last_price
    log_rate = np.log(max(anchor_price, 1e-8) / last_price) / anchor_bdays
    return float(max(last_price * np.exp(log_rate * target_bdays), 0))


def generate_comment(ticker: str, last_price: float,
                      forecasts: Dict[str, float]) -> str:
    """
    Build a concise, rule-based commentary from forecast values.
    Describes short-, medium- and long-term trend direction and magnitude.
    """
    def pct(col: str) -> Optional[float]:
        v = forecasts.get(col)
        if v is not None and last_price and last_price != 0:
            return (v - last_price) / last_price * 100.0
        return None

    def direction(p: Optional[float]) -> str:
        if p is None:
            return "flat"
        if p > 10:   return "strongly bullish"
        if p > 3:    return "bullish"
        if p > 0.5:  return "mildly bullish"
        if p < -10:  return "strongly bearish"
        if p < -3:   return "bearish"
        if p < -0.5: return "mildly bearish"
        return "sideways"

    parts: List[str] = []

    p1m = pct("price_1m")
    p6m = pct("price_6m")
    p1y = pct("price_1y")
    p5y = pct("price_5y")

    if p1m is not None:
        parts.append(
            f"The short-term (1-month) outlook for {ticker} is {direction(p1m)} "
            f"({p1m:+.1f}% vs current price of {last_price:.2f})."
        )

    if p6m is not None:
        v6m = forecasts["price_6m"]
        parts.append(
            f"At 6 months the model targets {v6m:.2f} ({p6m:+.1f}%), "
            f"a {direction(p6m)} medium-term signal."
        )

    if p1y is not None:
        v1y = forecasts["price_1y"]
        parts.append(
            f"The 1-year forecast stands at {v1y:.2f} ({p1y:+.1f}%)."
        )

    if p5y is not None:
        v5y = forecasts["price_5y"]
        parts.append(
            f"Over a 5-year horizon the model projects {v5y:.2f} "
            f"(cumulative {p5y:+.1f}%)."
        )

    if not parts:
        parts.append(
            f"Insufficient data to generate a reliable forecast for {ticker}."
        )

    return " ".join(parts)


def build_forecast_row(
    ticker: str,
    yhat: np.ndarray,
    last_price: float,
    extrapolate: Optional[str] = "1y",
) -> Dict[str, Any]:
    """
    Build a forecast result dict from a 1-D predicted price array.

    yhat[i] corresponds to business day i+1 ahead.

    extrapolate controls how horizons beyond len(yhat) are filled:
      "1y"   - log-trend from the 1-year forecast
      "6m1y" - 6-month trend, falling back to 1-year
      None   - skip horizons beyond the array
    """
    result: Dict[str, float] = {}
    for col, bdays in HORIZON_MAP:
        idx = bdays - 1
        if idx < len(yhat):
            val = float(np.asarray(yhat[idx]).reshape(-1)[0])
            result[col] = round(max(val, 0.0), 4)
        elif extrapolate == "6m1y":
            v6m = result.get("price_6m")
            v1y = result.get("price_1y")
            if v6m and v1y and v6m > 0 and last_price > 0:
                result[col] = round(
                    log_trend_extrapolate(last_price, v6m, 126, bdays), 4
                )
            elif v1y and last_price > 0:
                result[col] = round(
                    log_trend_extrapolate(last_price, v1y, 252, bdays), 4
                )
        elif extrapolate == "1y":
            v1y = result.get("price_1y")
            if v1y and last_price > 0:
                result[col] = round(
                    log_trend_extrapolate(last_price, v1y, 252, bdays), 4
                )

    comment = generate_comment(ticker, last_price, result)
    return {"ticker": ticker, "comment": comment, **result}


def save_forecast_results(
    rows: list,
    output_dir: Path,
    model_name: str,
    logger: logging.Logger,
) -> Path:
    """Write forecast rows to a date-stamped TSV."""
    today = date.today().isoformat()
    out_path = output_dir / f"{model_name}_osl_{today}_single_run.tsv"
    pd.DataFrame(rows).to_csv(out_path, sep="\t", index=False)
    logger.info("Saved %d rows -> %s", len(rows), out_path)
    return out_path


def setup_logger(name: str) -> logging.Logger:
    """Configure and return a logger with the standard forecast format."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    return logging.getLogger(name)
