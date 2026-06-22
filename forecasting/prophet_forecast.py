#!/usr/bin/env python3
"""
Prophet forecast for Oslo Stock Exchange tickers.

Prophet handles trend, weekly/yearly seasonality and naturally extrapolates
multi-year horizons. It is the most robust model for long-range (3-5 year)
forecasts in this set.

Runtime on 12 CPUs: ~5-10 minutes for all ~200 tickers.

Usage:
    python prophet_forecast.py [--output-dir PATH] [--workers N]
"""
import argparse
import logging
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Dict, Optional, Tuple

import pandas as pd
from tqdm import tqdm

from utils import (
    DATA_DIR,
    HORIZON_MAP,
    MAX_HORIZON_BDAYS,
    load_all_history,
    generate_comment,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _forecast_one(ticker: str, df: pd.DataFrame) -> Optional[Tuple[str, Dict]]:
    """Fit Prophet and return horizon forecasts for one ticker."""
    try:
        warnings.filterwarnings("ignore")
        from prophet import Prophet

        pdf = df.rename(columns={"Date": "ds", "Close": "y"})

        model = Prophet(
            daily_seasonality=False,
            weekly_seasonality=True,
            yearly_seasonality=True,
            changepoint_prior_scale=0.05,
            seasonality_mode="multiplicative",
            uncertainty_samples=0,  # skip uncertainty intervals for speed
        )
        model.fit(pdf)

        future = model.make_future_dataframe(periods=MAX_HORIZON_BDAYS, freq="B")
        fc = model.predict(future)

        last_date = df["Date"].max()
        future_fc = fc[fc["ds"] > last_date].reset_index(drop=True)

        result: Dict[str, float] = {}
        for col, bdays in HORIZON_MAP:
            idx = bdays - 1  # 0-indexed
            if idx < len(future_fc):
                result[col] = round(max(float(future_fc.iloc[idx]["yhat"]), 0), 4)

        last_price = float(df["Close"].iloc[-1])
        comment = generate_comment(ticker, last_price, result)
        return ticker, {"ticker": ticker, "comment": comment, **result}

    except Exception as exc:
        logger.warning("Prophet failed for %s: %s", ticker, exc)
        return None


def main(output_dir: Path, workers: int) -> None:
    logger.info("Loading history…")
    history = load_all_history()
    logger.info("Loaded %d tickers. Starting Prophet forecasts with %d workers…",
                len(history), workers)

    rows = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_forecast_one, ticker, df): ticker
            for ticker, df in history.items()
        }
        for fut in tqdm(as_completed(futures), total=len(futures), desc="Prophet"):
            res = fut.result()
            if res is not None:
                _, row = res
                rows.append(row)

    today = date.today().isoformat()
    out_path = output_dir / f"prophet_osl_{today}_single_run.tsv"
    pd.DataFrame(rows).to_csv(out_path, sep="\t", index=False)
    logger.info("Saved %d rows → %s", len(rows), out_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DATA_DIR,
                        help="Directory to write the TSV file (default: ../data)")
    parser.add_argument("--workers", type=int, default=8,
                        help="Parallel workers (default: 8, max useful: 12)")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    main(args.output_dir, args.workers)
