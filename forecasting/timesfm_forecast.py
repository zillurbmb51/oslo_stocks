#!/usr/bin/env python3
"""
Google TimesFM zero-shot forecast for Oslo Stock Exchange tickers.

>>> DEEP LEARNING (pre-trained transformer, ~200M parameters) <<<
TimesFM is a foundation time-series model trained by Google on ~100B real-world
time points. It requires NO fine-tuning — just feed in the history and it predicts.

Key properties:
- Zero-shot: no training required on your data
- Pre-trained checkpoint: ~800 MB download from HuggingFace (first run only)
- Horizon: TimesFM outputs up to 512 steps; we use 252 (1 year) then extrapolate
- CPU runtime: ~60-120 minutes for 200 tickers (batch_size tunable)
- GPU (if available): ~5-10 minutes

Runtime notes:
  - First run downloads the model (~800 MB) to ~/.cache/huggingface/
  - Use HF_HOME env var to redirect the cache if needed
  - Set --batch-size lower (e.g. 4) if you hit OOM on RAM

Usage:
    python timesfm_forecast.py [--output-dir PATH] [--batch-size N]
    HF_HOME=/path/to/cache python timesfm_forecast.py
"""
import argparse
import warnings
from pathlib import Path
from typing import List

import numpy as np
from tqdm import tqdm

from utils import (
    DATA_DIR,
    load_all_history,
    build_forecast_row,
    save_forecast_results,
    setup_logger,
)

logger = setup_logger(__name__)

TIMESFM_HORIZON = 252   # 1 year; extrapolate beyond


def main(output_dir: Path, batch_size: int) -> None:
    warnings.filterwarnings("ignore")

    import timesfm  # pip: timesfm[torch]

    logger.info("Loading TimesFM checkpoint (downloads on first run)…")
    # Compatibility across timesfm package variants (API/name may differ).
    # Current installed package appears to expose:
    #   - timesfm.TimesFM_2p5_200M_torch
    #   - timesfm.ForecastConfig
    # We handle both the older (TimesFm*) and newer (TimesFM_*) APIs.

    def _pick(attr_candidates, namespace):
        for name in attr_candidates:
            if hasattr(namespace, name):
                return getattr(namespace, name)
        return None

    TimesFmCls = _pick(["TimesFm", "TimesFM"], timesfm)
    HparamsCls = _pick(["TimesFmHparams", "TimesFMHparams"], timesfm)
    CheckpointCls = _pick(["TimesFmCheckpoint", "TimesFMCheckpoint"], timesfm)

    if TimesFmCls and HparamsCls and CheckpointCls:
        tfm = TimesFmCls(
            hparams=HparamsCls(
                backend="cpu",
                per_core_batch_size=batch_size,
                horizon_len=TIMESFM_HORIZON,
            ),
            checkpoint=CheckpointCls(
                huggingface_repo_id="google/timesfm-1.0-200m-pytorch"
            ),
        )
    else:
        # Newer API
        TimesFmNewCls = _pick(["TimesFM_2p5_200M_torch"], timesfm)
        ForecastConfigCls = _pick(["ForecastConfig"], timesfm)
        if TimesFmNewCls is None or ForecastConfigCls is None:
            raise AttributeError(
                "Unsupported timesfm API. Found top-level symbols: "
                f"{sorted([s for s in dir(timesfm) if not s.startswith('_')])[:80]}"
            )

        # ForecastConfig fields vary by version; we pass what we know.
        # We also set horizon_len to match script expectation.
        # Newer ForecastConfig uses max_horizon/max_context (names differ from older API).
        cfg = ForecastConfigCls(
            max_context=0,
            max_horizon=TIMESFM_HORIZON,
            per_core_batch_size=batch_size,
            return_backcast=False,
        )
        tfm = TimesFmNewCls(config=cfg)
        # Newer TimesFM requires compilation before calling forecast().
        # In this package version, compile() expects a forecast_config.
        if hasattr(tfm, "compile"):
            try:
                tfm.compile(forecast_config=cfg)
            except TypeError:
                # Fallback for alternative parameter naming
                tfm.compile(cfg)





    logger.info("Loading history…")
    history = load_all_history()
    logger.info("Loaded %d tickers.", len(history))

    tickers: List[str] = list(history.keys())
    rows = []

    for i in tqdm(range(0, len(tickers), batch_size), desc="TimesFM"):
        batch_tickers = tickers[i : i + batch_size]
        # TimesFM accepts variable-length sequences (list of 1-D arrays)
        contexts = [history[t]["Close"].values.astype(np.float32) for t in batch_tickers]
        # Newer timesfm versions may not accept `freq=` in forecast().
        # We keep the variable for compatibility, but do not pass it.
        # freq = [0] * len(contexts)  # 0 = high-freq / business-daily

        # Newer timesfm API signature: forecast(horizon, inputs)
        # TimesFM_2p5 uses an internal patch size (p). For this build, p=32.
        # It expects the context length to be compatible with p.
        p = 32
        # Build a fixed context length (multiple of p) for the whole batch.
        # TimesFM expects the list of inputs to be convertible to a uniform array.
        context_multiples = []
        normalized = []
        for c in contexts:
            c = np.asarray(c, dtype=np.float32)
            n = (len(c) // p) * p
            if n <= 0:
                n = p
                c = np.pad(c, (p - len(c), 0), mode="edge")
            else:
                c = c[-n:]
            normalized.append(c)
            context_multiples.append(len(c))

        target_len = max(context_multiples) if context_multiples else p
        if target_len % p != 0:
            target_len = (target_len // p) * p
            if target_len <= 0:
                target_len = p

        patched_contexts = []
        for c in normalized:
            if len(c) < target_len:
                c = np.pad(c, (target_len - len(c), 0), mode="edge")
            elif len(c) > target_len:
                c = c[-target_len:]
            patched_contexts.append(c)

        fc = tfm.forecast(TIMESFM_HORIZON, patched_contexts)



        # Signature returns (backcast, yhat)
        _, yhat_batch = fc
        # yhat_batch shape: (batch, horizon)



        for j, ticker in enumerate(batch_tickers):
            yhat = np.asarray(yhat_batch[j]).reshape(-1)
            last_price = float(history[ticker]["Close"].iloc[-1])
            rows.append(build_forecast_row(ticker, yhat, last_price, extrapolate="1y"))

    save_forecast_results(rows, output_dir, "timesfm", logger)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DATA_DIR)
    parser.add_argument(
        "--batch-size", type=int, default=16,
        help="Number of tickers per inference batch. Reduce if hitting OOM (default: 16)."
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    main(args.output_dir, args.batch_size)
