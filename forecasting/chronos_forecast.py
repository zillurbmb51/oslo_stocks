#!/usr/bin/env python3
"""
Amazon Chronos zero-shot forecast for Oslo Stock Exchange tickers.

>>> DEEP LEARNING (pre-trained T5 transformer) <<<
Chronos is a language-model-style time-series foundation model by Amazon.
It quantises prices into discrete tokens and uses a T5 encoder-decoder to
predict future token distributions — exactly like a language model, but for
numbers.

Key properties:
- Zero-shot: no fine-tuning; just inference on your data
- Checkpoint options (trade accuracy vs speed):
    chronos-t5-tiny    (~8M params,  ~50 MB) — fastest
    chronos-t5-mini    (~20M params, ~90 MB)
    chronos-t5-small   (~46M params, ~190 MB) ← default (best CPU trade-off)
    chronos-t5-base    (~200M params, ~800 MB) — slower on CPU
    chronos-t5-large   (~710M params, ~3 GB)  — use only with GPU
- Horizon: we run h=252 steps, then extrapolate beyond 1 year
- CPU runtime: ~60-120 min for 200 tickers (small), ~30 min (tiny)

Usage:
    python chronos_forecast.py [--output-dir PATH] [--checkpoint CKPT]
                               [--batch-size N] [--n-samples N]
"""
import argparse
import logging
import warnings
from datetime import date
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd
import torch
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

CHRONOS_HORIZON = 252


def main(output_dir: Path, checkpoint: str, batch_size: int, n_samples: int) -> None:
    warnings.filterwarnings("ignore")

    from chronos import ChronosPipeline  # pip: chronos-forecasting

    device_map = "cpu"
    dtype = torch.float32

    logger.info("Loading Chronos checkpoint '%s' (downloads on first run)…", checkpoint)
    pipeline = ChronosPipeline.from_pretrained(
        checkpoint,
        device_map=device_map,
        torch_dtype=dtype,
    )

    logger.info("Loading history…")
    history = load_all_history()
    logger.info("Loaded %d tickers.", len(history))

    tickers: List[str] = list(history.keys())
    rows = []

    for i in tqdm(range(0, len(tickers), batch_size), desc="Chronos"):
        batch_tickers = tickers[i : i + batch_size]

        contexts = [
            torch.tensor(
                history[t]["Close"].values.astype(np.float32),
                dtype=torch.float32
            )
            for t in batch_tickers
        ]

        # forecast() returns quantile forecasts; shape (batch, n_samples, horizon)
        # ChronosPipeline API expects inputs as the positional/keyword argument `inputs`
        # (older examples used `context`; newer versions use `inputs`).
        forecast = pipeline.predict(
            inputs=contexts,
            prediction_length=CHRONOS_HORIZON,
            num_samples=n_samples,
        )
        # Use median (50th percentile) across samples
        median_fc = np.median(forecast.numpy(), axis=1)  # (batch, horizon)

        for j, ticker in enumerate(batch_tickers):
            yhat = median_fc[j]
            last_price = float(history[ticker]["Close"].iloc[-1])

            result: Dict[str, float] = {}
            for col, bdays in HORIZON_MAP:
                idx = bdays - 1
                if idx < len(yhat):
                    result[col] = round(max(float(yhat[idx]), 0.0), 4)
                else:
                    v1y = result.get("price_1y")
                    if v1y and last_price > 0:
                        result[col] = round(
                            log_trend_extrapolate(last_price, v1y, 252, bdays), 4
                        )

            comment = generate_comment(ticker, last_price, result)
            rows.append({"ticker": ticker, "comment": comment, **result})

    today = date.today().isoformat()
    out_path = output_dir / f"chronos_osl_{today}_single_run.tsv"
    pd.DataFrame(rows).to_csv(out_path, sep="\t", index=False)
    logger.info("Saved %d rows → %s", len(rows), out_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DATA_DIR)
    parser.add_argument(
        "--checkpoint", type=str,
        default="amazon/chronos-t5-small",
        help="HuggingFace checkpoint. Options: "
             "amazon/chronos-t5-tiny | mini | small | base (default: small)"
    )
    parser.add_argument(
        "--batch-size", type=int, default=16,
        help="Tickers per inference batch (default: 16). Reduce if OOM."
    )
    parser.add_argument(
        "--n-samples", type=int, default=20,
        help="Posterior samples for median estimate (default: 20)."
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    main(args.output_dir, args.checkpoint, args.batch_size, args.n_samples)
