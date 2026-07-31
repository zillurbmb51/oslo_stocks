#!/usr/bin/env python3
"""
N-HiTS (Neural Hierarchical Interpolation for Time Series) forecast.

>>> THIS IS DEEP LEARNING <<<
N-HiTS is a multi-stack neural network that learns both trend and seasonal
components via hierarchical interpolation. It runs entirely on CPU and trains
a global model across all tickers simultaneously (shared parameters), which
makes it data-efficient for tickers with short histories.

Key properties:
- Global model: all ~200 tickers trained together
- No GPU required: runs on CPU in reasonable time (~30-60 min for 200 tickers)
- Horizon limit: NeuralForecast trains to h=252 (1 year); beyond that we
  extrapolate using the log-trend implied by the 6m→1y slope.

Runtime on 12 CPUs: ~30-60 minutes.

Usage:
    python nhits_forecast.py [--output-dir PATH] [--max-steps N]
"""
import argparse
import os
import warnings
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from utils import (
    DATA_DIR,
    load_all_history,
    build_forecast_row,
    save_forecast_results,
    setup_logger,
)

logger = setup_logger(__name__)

# N-HiTS trains up to 1 year ahead (252 business days).
# Longer horizons are extrapolated via log-trend from the 6m→1y forecast slope.
NHITS_HORIZON = 252


def main(output_dir: Path, max_steps: int) -> None:
    warnings.filterwarnings("ignore")
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

    from neuralforecast import NeuralForecast
    from neuralforecast.models import NHITS

    logger.info("Loading history…")
    history = load_all_history()
    logger.info("Loaded %d tickers.", len(history))

    # Build long-format DataFrame for NeuralForecast
    records = []
    for ticker, df in history.items():
        tmp = df.rename(columns={"Date": "ds", "Close": "y"})
        tmp["unique_id"] = ticker
        records.append(tmp[["unique_id", "ds", "y"]])

    nf_df = pd.concat(records, ignore_index=True)
    nf_df["ds"] = pd.to_datetime(nf_df["ds"])
    nf_df = nf_df.sort_values(["unique_id", "ds"]).reset_index(drop=True)

    logger.info("Total rows in training frame: %d", len(nf_df))

    model = NHITS(
        h=NHITS_HORIZON,
        input_size=NHITS_HORIZON,        # look back 1 year
        max_steps=max_steps,
        learning_rate=1e-3,
        batch_size=32,
        scaler_type="standard",
        n_freq_downsample=[4, 2, 1],
        stack_types=["identity", "identity", "identity"],
        n_blocks=[1, 1, 1],
        mlp_units=[[256, 256], [256, 256], [256, 256]],
        interpolation_mode="linear",
        # NeuralForecast expects a loss object (not a plain dict) in this version.
        # Use the model default MAE loss when `loss` is not configured.
        # Disable early stopping to avoid val_size/val_df requirement, and also
        # ensure short series can still be used.
        early_stop_patience_steps=0,
        start_padding_enabled=True,

        val_check_steps=50,
        random_seed=42,
        # Compatibility: older/newer neuralforecast versions don't accept
        # these lightning trainer kwargs.
        # num_workers_loader=4,
        # drop_last_loader=False,

    )

    nf = NeuralForecast(models=[model], freq="B")
    logger.info("Fitting N-HiTS global model (max_steps=%d)…", max_steps)
    nf.fit(nf_df)

    logger.info("Generating forecasts…")
    fc_df = nf.predict()

    # fc_df has columns: unique_id, ds, NHITS
    rows = []
    for ticker, df in tqdm(history.items(), desc="Post-processing N-HiTS"):
        ticker_fc = fc_df[fc_df["unique_id"] == ticker].sort_values("ds").reset_index(drop=True)
        if ticker_fc.empty:
            logger.warning("No forecast for %s", ticker)
            continue

        yhat = ticker_fc["NHITS"].values
        last_price = float(df["Close"].iloc[-1])
        rows.append(build_forecast_row(ticker, yhat, last_price, extrapolate="6m1y"))

    save_forecast_results(rows, output_dir, "nhits", logger)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DATA_DIR)
    parser.add_argument(
        "--max-steps", type=int, default=500,
        help="Training steps for N-HiTS. 500 is a good default; "
             "increase to 1000 for better accuracy at cost of longer runtime."
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    main(args.output_dir, args.max_steps)
