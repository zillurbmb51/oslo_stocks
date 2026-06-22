#!/usr/bin/env python3
"""
XGBoost multi-horizon direct forecast for Oslo Stock Exchange tickers.

Uses lag prices, rolling statistics, and log-returns as features.
Trains one model per ticker using a direct multi-output strategy
(separate XGBoost for each of the 14 forecast horizons).

Fast, interpretable, and often competitive with neural models on tabular data.
Parallelized across tickers.

Runtime on 12 CPUs: ~10-20 minutes for all ~200 tickers.

Usage:
    python xgboost_forecast.py [--output-dir PATH] [--workers N]
"""
import argparse
import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd
from tqdm import tqdm

from utils import (
    DATA_DIR,
    HORIZON_MAP,
    load_all_history,
    generate_comment,
    log_trend_extrapolate,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Feature engineering configuration
LAG_DAYS = [1, 2, 3, 5, 10, 21, 63, 126, 252]
ROLL_WINDOWS = [5, 10, 21, 63, 126, 252]
MIN_TRAIN_SAMPLES = 60  # minimum training rows per horizon


def _make_features(closes: np.ndarray) -> np.ndarray:
    """Build a 1-D feature vector from a close price series."""
    feats = []
    last = closes[-1]

    # Log-returns at various lookback lags
    for lag in LAG_DAYS:
        if len(closes) > lag:
            feats.append(np.log(last / closes[-lag - 1]))
        else:
            feats.append(0.0)

    # Rolling mean ratio (how far price is from its average)
    for w in ROLL_WINDOWS:
        if len(closes) >= w:
            feats.append(last / (closes[-w:].mean() + 1e-8) - 1.0)
        else:
            feats.append(0.0)

    # Rolling normalized volatility
    for w in ROLL_WINDOWS:
        if len(closes) >= w:
            m = closes[-w:].mean()
            feats.append(closes[-w:].std() / (m + 1e-8))
        else:
            feats.append(0.0)

    return np.array(feats, dtype=np.float32)


def _build_dataset(closes: np.ndarray, horizon: int
                   ) -> Tuple[np.ndarray, np.ndarray]:
    """
    Build (X, y) for a single horizon:
      X[i] = feature vector at position i
      y[i] = log-return from closes[i] to closes[i + horizon]
    """
    X_list, y_list = [], []
    n = len(closes)
    for i in range(n - horizon):
        x = _make_features(closes[: i + 1])
        log_ret = np.log(closes[i + horizon] / (closes[i] + 1e-8))
        X_list.append(x)
        y_list.append(log_ret)
    return np.array(X_list, dtype=np.float32), np.array(y_list, dtype=np.float32)


def _forecast_one(ticker: str, df: pd.DataFrame) -> Optional[Tuple[str, Dict]]:
    try:
        from xgboost import XGBRegressor

        closes = df["Close"].values.astype(np.float64)
        last_price = float(closes[-1])
        result: Dict[str, float] = {}

        for col, horizon_bdays in HORIZON_MAP:
            if len(closes) < horizon_bdays + MIN_TRAIN_SAMPLES:
                # Not enough history: fall back to log-trend from last 252 days
                n = min(252, len(closes) - 1)
                if n > 0:
                    result[col] = round(
                        log_trend_extrapolate(last_price, closes[-n - 1],
                                              -n, horizon_bdays), 4
                    )
                continue

            X, y = _build_dataset(closes, horizon_bdays)
            if len(X) < MIN_TRAIN_SAMPLES:
                continue

            model = XGBRegressor(
                n_estimators=200,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                min_child_weight=5,
                random_state=42,
                n_jobs=1,       # 1 per ticker; outer parallelism handles concurrency
                verbosity=0,
            )
            model.fit(X, y)

            x_latest = _make_features(closes).reshape(1, -1)
            log_ret_pred = float(model.predict(x_latest)[0])
            predicted_price = last_price * np.exp(log_ret_pred)
            result[col] = round(max(predicted_price, 0.0), 4)

        comment = generate_comment(ticker, last_price, result)
        return ticker, {"ticker": ticker, "comment": comment, **result}

    except Exception as exc:
        logger.warning("XGBoost failed for %s: %s", ticker, exc)
        return None


def main(output_dir: Path, workers: int) -> None:
    logger.info("Loading history…")
    history = load_all_history()
    logger.info("Loaded %d tickers. Starting XGBoost forecasts with %d workers…",
                len(history), workers)

    rows = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_forecast_one, ticker, df): ticker
            for ticker, df in history.items()
        }
        for fut in tqdm(as_completed(futures), total=len(futures), desc="XGBoost"):
            res = fut.result()
            if res:
                _, row = res
                rows.append(row)

    today = date.today().isoformat()
    out_path = output_dir / f"xgboost_osl_{today}_single_run.tsv"
    pd.DataFrame(rows).to_csv(out_path, sep="\t", index=False)
    logger.info("Saved %d rows → %s", len(rows), out_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    main(args.output_dir, args.workers)
