# Adaptive ensemble backtest and forecast archive

Run from the project root:

```sh
python -m pip install -r forecasting/requirements-backtest.txt
python -m unittest discover -s tests -p 'test_backtest.py' -v
python forecasting/walk_forward_backtest.py --as-of 2026-10-06
python forecasting/report_backtest.py
```

For subsequent runs, supply the data cutoff explicitly with `--as-of YYYY-MM-DD`.
The script reads the existing workbook and actual-price CSV; it does not download
prices, place trades, or schedule itself. Update those sources before rerunning.
Use `--ticker VEI` for a single ticker and a separate `--output-dir` to retain
multiple result exports. The SQLite archive retains multiple experiments.

## Experiment

Horizon lengths are exactly **1, 5, 20, 30, 60, and 100 XOSL exchange sessions**.
Forecasts are issued after the origin day's close, using that close. They are
not forecasts executable at that same close. Missing quotes remain missing;
there is no forward fill and no shifting the target to the next available quote.

The default scoring window is the last 252 exchange sessions in the dataset.
Earlier history initializes each ticker/horizon's error history. At least 121
valid observations and 61 consecutive session closes are needed to issue a
forecast. Every model is scored on the same available origin/target pairs
within each ticker and horizon. Longer horizons have fewer completed outcomes.

Base models:

- `no_change`: zero log return; projected price equals the origin close.
- `momentum_5`: mean of the latest five daily log returns, multiplied by horizon.
- `drift_60`: mean of the latest 60 daily log returns, multiplied by horizon.

Comparators:

- `corrected_momentum`: momentum plus the median of the latest 60 *completed*
  momentum errors, after at least 20 outcomes. Before that it is uncorrected.
- `equal_ensemble`: equal mean of the three base log-return predictions.
- `adaptive_ensemble`: inverse rolling mean absolute log-return-error weights,
  shrunk 20% toward equal weights. Weights use at most 60 completed outcomes,
  separately for each ticker/horizon. Until 20 outcomes exist, use no-change.

These are transparent, inexpensive reference models. This experiment does
**not** retrospectively claim to evaluate Chronos, NHITS, Prophet, TimesFM or
XGBoost: their saved files do not provide enough verified historical runs and
training cutoffs at these exact horizons. No 21-day forecast is relabeled as
20 days, and no 63-day forecast as 60 days.

The correction bug was fixed by queuing forecasts until their target session
has closed. The original script appended outcomes immediately, leaking future
information for overlapping multi-day forecasts. It also excluded the current
origin close from momentum features; those features now include it.

## Outputs

- `data/forecast_outcomes.sqlite`: dated, keyed predictions and outcomes.
- `data/adaptive_backtest/summary.csv`: pooled and equal-ticker error metrics.
- `data/adaptive_backtest/per_ticker_metrics.csv`: ticker/horizon/model results.
- `data/adaptive_backtest/data_quality_flags.csv`: price jumps needing inspection.
- `data/adaptive_backtest/RESULTS.txt`: readable results and actual date coverage.
- `data/adaptive_backtest/coverage.csv`: scored, missing and pending pairs per ticker/horizon.
- `data/adaptive_backtest/nonoverlapping_metrics.csv`: fixed-phase robustness check.
- `data/adaptive_backtest/latest_archived_ensemble.csv`: latest eligible archived predictions, which may be older than the latest data.
- `data/adaptive_backtest/run_metadata.json`: source hashes, experiment ID,
  code hash, parameters, cutoff, calendar version and coverage.

MAE, RMSE and bias are in **percentage points of log return**, not currency or
MAPE. Directional accuracy counts positive, negative and exactly zero as three
separate directions. No-change therefore earns direction credit only on zero
realized return. These are forecasting metrics, not trading strategy returns.

Archive tables:

- `experiments`: run settings and source fingerprints.
- `forecasts`: immutable predictions keyed by experiment/ticker/origin/horizon/model;
  includes target date, training cutoff, feedback count and adaptive weights.
- `outcomes`: resolved/pending/missing_actual, observed price and realized return.
- `legacy_forecasts`: original TSV price predictions keyed by source SHA-256,
  ticker and original horizon. Filename dates are recorded as filename dates,
  not asserted to be verified forecast creation times or training cutoffs.

The archive explicitly labels reconstructed predictions `reconstructed_backtest`.
Legacy records are excluded from scoring until their timing can be verified.
Reruns are idempotent within an experiment and do not overwrite predictions.
A new source snapshot creates a new experiment. Reruns also resolve pending or
missing outcomes in earlier experiments when exact target-date closes become
available. Already resolved older outcomes remain frozen to their snapshot.

For example, inspect the newest experiment using:

```sql
SELECT experiment_id, created_at, metadata FROM experiments ORDER BY created_at DESC;
SELECT ticker, origin_date, target_date, horizon_days, weights
FROM forecasts WHERE model = 'adaptive_ensemble' LIMIT 10;
SELECT status, COUNT(*) FROM outcomes GROUP BY status;
```

## Interpretation limits

The source prices are not a verified point-in-time, corporate-action-adjusted
feed. The archive cannot recover their historical publication timestamps or
remove survivorship bias from the workbook universe. Data revisions and large
price jumps can distort results; inspect the quality flags before deployment.
Reported availability assumes the target close was known after that session.
Only the algorithm's temporal information flow is tested for leakage.

Daily evaluation windows overlap at longer horizons. Observation counts are not
independent sample counts; no statistical significance or profit claim follows
from a lower MAE. Weights adapt sequentially, but the fixed window and shrinkage
parameters are not optimized on the scored window. Compare against no-change
before using an ensemble in the website or calling it an improvement.

For session repair and explicit adjusted-history inputs, see [DATA_REPAIR.md](DATA_REPAIR.md). Adjusted snapshots never resolve pending forecasts from a different price basis.
