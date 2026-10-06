#!/usr/bin/env python3
"""After-close, prequential Oslo-session backtest and auditable SQLite archive.

Predictions are reconstructed, not historical live forecasts. Only outcomes
whose target session has closed can update weights or residual correction.
"""
import argparse
from collections import deque
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3

import numpy as np
import pandas as pd
import exchange_calendars as xcals

from utils import DATA_DIR, HORIZON_MAP, load_all_history

HORIZONS = (1, 5, 20, 30, 60, 100)
BASE_MODELS = ("no_change", "momentum_5", "drift_60")
MODELS = (*BASE_MODELS, "corrected_momentum", "equal_ensemble", "adaptive_ensemble")
VERSION = "adaptive-v2"


def clean_history(history):
    frame = history[["Date", "Close"]].copy()
    frame["Date"] = pd.to_datetime(frame["Date"], utc=True).dt.tz_convert(None).dt.normalize()
    frame["Close"] = pd.to_numeric(frame["Close"], errors="coerce")
    frame = frame.dropna(subset=["Date"]).drop_duplicates("Date", keep="last").sort_values("Date")
    frame.loc[~np.isfinite(frame.Close) | (frame.Close <= 0), "Close"] = np.nan
    return frame.set_index("Date").Close


def session_calendar(start, end):
    calendar = xcals.get_calendar("XOSL", start=start, end=end)
    return calendar.sessions.tz_localize(None) if calendar.sessions.tz is not None else calendar.sessions


def forecast_log_return(closes, horizon):
    return float(np.diff(np.log(closes[-6:])).mean() * horizon)


def evaluate(ticker, history, min_train=120, *, sessions=None, evaluation_start=None,
             window=60, min_feedback=20, as_of=None):
    """Yield archive rows. Actual closes assumed available after their session.

    Reindexing onto XOSL prevents missing quotes from shortening a horizon.
    The target date is always origin + h exchange sessions, never h quote rows.
    """
    series = clean_history(history)
    if as_of is not None:
        series = series.loc[:pd.Timestamp(as_of)]
    if series.empty:
        return
    if sessions is None:
        sessions = session_calendar(series.index.min(), series.index.max() + pd.Timedelta(days=250))
    prices = series.reindex(sessions).to_numpy(float)
    valid_origins = np.flatnonzero(np.isfinite(prices))
    if not len(valid_origins):
        return
    last = valid_origins[-1]
    cutoff = pd.Timestamp(as_of) if as_of is not None else sessions[last]
    observation_counts = np.cumsum(np.isfinite(prices))
    # A separate feedback queue per horizon prevents mixing target distances.
    for horizon in HORIZONS:
        pending = deque()
        errors = deque(maxlen=window)
        residuals = deque(maxlen=window)
        for origin in range(min_train, last + 1):
            # Resolve old forecasts BEFORE issuing today's after-close forecast.
            while pending and pending[0][0] <= origin:
                target, old_base, old_price = pending.popleft()
                if np.isfinite(prices[target]):
                    realized = np.log(prices[target] / old_price)
                    errors.append(np.abs(old_base - realized))
                    residuals.append(realized - old_base[1])
            if observation_counts[origin] < min_train + 1 or origin + horizon >= len(sessions):
                continue
            recent = prices[origin - 60:origin + 1]
            if len(recent) < 61 or not np.isfinite(recent).all():
                continue
            price = prices[origin]
            base = np.array([0., forecast_log_return(recent, horizon),
                             np.log(recent[-1] / recent[0]) / 60 * horizon])
            feedback_count = len(errors)
            if feedback_count >= min_feedback:
                losses = np.mean(errors, axis=0)
                weights = 1 / np.maximum(losses, 1e-6)
                weights /= weights.sum()
                # Fixed shrinkage avoids extreme weights from a small sample.
                weights = .8 * weights + .2 / len(BASE_MODELS)
            else:
                weights = np.array([1., 0., 0.])
            correction = float(np.median(residuals)) if len(residuals) >= min_feedback else 0.
            predictions = [*base, base[1] + correction, base.mean(), float(weights @ base)]
            target = origin + horizon
            pending.append((target, base, price))
            if evaluation_start is not None and sessions[origin] < evaluation_start:
                continue
            actual = prices[target] if target <= last else np.nan
            actual_return = np.log(actual / price) if np.isfinite(actual) else np.nan
            status = "resolved" if np.isfinite(actual) else ("pending" if sessions[target] > cutoff else "missing_actual")
            for model, prediction in zip(MODELS, predictions):
                yield dict(ticker=ticker, origin_date=str(sessions[origin].date()),
                           target_date=str(sessions[target].date()), horizon_days=horizon,
                           model=model, origin_price=float(price), predicted_log_return=float(prediction),
                           predicted_price=float(price * np.exp(np.clip(prediction, -700, 700))),
                           actual_price=float(actual) if np.isfinite(actual) else None,
                           actual_log_return=float(actual_return) if np.isfinite(actual_return) else None,
                           status=status, feedback_count=feedback_count,
                           weights=json.dumps(dict(zip(BASE_MODELS, weights))) if model == "adaptive_ensemble" else None,
                           provenance="reconstructed_backtest", training_cutoff=str(sessions[origin].date()))


def open_archive(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript('''
    PRAGMA foreign_keys=ON;
    CREATE TABLE IF NOT EXISTS experiments (
      experiment_id TEXT PRIMARY KEY, created_at TEXT, metadata TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS forecasts (
      experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
      ticker TEXT, origin_date TEXT, target_date TEXT, horizon_days INTEGER,
      model TEXT, origin_price REAL, predicted_log_return REAL, predicted_price REAL,
      feedback_count INTEGER, weights TEXT, provenance TEXT, training_cutoff TEXT,
      PRIMARY KEY(experiment_id,ticker,origin_date,horizon_days,model));
    CREATE TABLE IF NOT EXISTS outcomes (
      experiment_id TEXT, ticker TEXT, origin_date TEXT, horizon_days INTEGER, model TEXT,
      target_date TEXT, actual_price REAL, actual_log_return REAL, status TEXT,
      availability_assumption TEXT, PRIMARY KEY(experiment_id,ticker,origin_date,horizon_days,model));
    CREATE TABLE IF NOT EXISTS legacy_forecasts (
      source_sha256 TEXT, source_file TEXT, ticker TEXT, model TEXT,
      filename_run_date TEXT, horizon_days INTEGER, predicted_price REAL,
      provenance TEXT, PRIMARY KEY(source_sha256,ticker,horizon_days));
    ''')
    return db


def archive_rows(db, experiment_id, rows):
    forecast_columns = ('ticker','origin_date','target_date','horizon_days','model','origin_price',
                        'predicted_log_return','predicted_price','feedback_count','weights','provenance','training_cutoff')
    db.executemany('INSERT OR IGNORE INTO forecasts VALUES (' + ','.join('?' * 13) + ')',
                   [(experiment_id, *(row[c] for c in forecast_columns)) for row in rows])
    db.executemany('INSERT OR REPLACE INTO outcomes VALUES (' + ','.join('?' * 10) + ')',
                   [(experiment_id, r['ticker'], r['origin_date'], r['horizon_days'], r['model'],
                     r['target_date'], r['actual_price'], r['actual_log_return'], r['status'],
                     'target session close; historical publication time not recorded') for r in rows])
    db.commit()


def resolve_archived_outcomes(db, histories, as_of, compatible_experiments=None):
    """Resolve pending/missing records without changing any stored prediction.

    Historical outcomes already present are frozen to their experiment snapshot.
    A new experiment captures corrected source prices on subsequent executions.
    """
    updates = []
    for ticker, history in histories.items():
        prices = clean_history(history).loc[:pd.Timestamp(as_of)]
        pending = db.execute("""SELECT f.experiment_id,f.origin_date,f.horizon_days,f.model,
            f.target_date,f.origin_price FROM forecasts f JOIN outcomes o USING
            (experiment_id,ticker,origin_date,horizon_days,model)
            WHERE f.ticker=? AND o.status != 'resolved' AND f.target_date<=?""",
            (ticker, as_of)).fetchall()
        for experiment, origin, horizon, model, target, origin_price in pending:
            if compatible_experiments is not None and experiment not in compatible_experiments:
                continue
            actual = prices.get(pd.Timestamp(target), np.nan)
            if np.isfinite(actual):
                updates.append((float(actual), float(np.log(actual / origin_price)),
                                'resolved', experiment, ticker, origin, horizon, model))
            else:
                updates.append((None, None, 'missing_actual', experiment, ticker, origin, horizon, model))
    db.executemany("""UPDATE outcomes SET actual_price=?,actual_log_return=?,status=?
        WHERE experiment_id=? AND ticker=? AND origin_date=? AND horizon_days=? AND model=?""", updates)
    db.commit()
    return sum(row[2] == 'resolved' for row in updates)


def import_legacy(db, directory):
    count = 0
    # Only files with the known price-column schema; do not infer cutoffs from names.
    for path in sorted(directory.glob('*_single_run.tsv')):
        match = re.match(r'(.+)_osl_(\d{4}-\d{2}-\d{2})_single_run.tsv$', path.name)
        if not match:
            continue
        frame = pd.read_csv(path, sep='\t', dtype={'ticker': str})
        if 'ticker' not in frame:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows = []
        for record in frame.to_dict('records'):
            for column, horizon in HORIZON_MAP:
                value = pd.to_numeric(record.get(column), errors='coerce')
                if pd.notna(value) and np.isfinite(value):
                    rows.append((digest, path.name, str(record['ticker']), match[1], match[2], horizon,
                                 float(value), 'legacy_unverified_cutoff_and_target_date'))
        before = db.total_changes
        db.executemany('INSERT OR IGNORE INTO legacy_forecasts VALUES (?,?,?,?,?,?,?,?)', rows)
        count += db.total_changes - before
    db.commit()
    return count


def summaries(frame, keys):
    resolved = frame[frame.status == 'resolved'].copy()
    if resolved.empty:
        return pd.DataFrame(columns=[*keys,"observations","mae_log_return_pct","bias_log_return_pct","directional_accuracy","rmse_log_return_pct"])
    resolved['error'] = (resolved.predicted_log_return - resolved.actual_log_return) * 100
    resolved['absolute_error'] = resolved.error.abs()
    resolved['squared_error'] = resolved.error ** 2
    resolved['direction_correct'] = np.sign(resolved.predicted_log_return) == np.sign(resolved.actual_log_return)
    summary = resolved.groupby(keys).agg(observations=('error','size'), mae_log_return_pct=('absolute_error','mean'),
                                         mse=('squared_error','mean'), bias_log_return_pct=('error','mean'),
                                         directional_accuracy=('direction_correct','mean')).reset_index()
    summary['rmse_log_return_pct'] = np.sqrt(summary.pop('mse'))
    summary['directional_accuracy'] *= 100
    return summary


def main(args):
    if args.min_train < 60 or args.evaluation_sessions < 1 or args.window < 1 or not 1 <= args.min_feedback <= args.window:
        raise SystemExit('Require min-train >= 60, evaluation-sessions > 0 and 1 <= min-feedback <= window')
    if args.history_file:
        from repair_history import load_validated_history
        histories = load_validated_history(args.history_file, args.price_basis)
        price_basis = 'provider_' + args.price_basis
    else:
        histories = load_all_history()
        price_basis = 'legacy_unverified'
    if args.ticker:
        histories = {args.ticker.upper(): histories[args.ticker.upper()]}
    histories = {t: h[pd.to_datetime(h.Date) <= pd.Timestamp(args.as_of)] for t,h in histories.items()}
    histories = {t:h for t,h in histories.items() if len(h) > args.min_train}
    if not histories:
        raise SystemExit('No eligible history')
    start = min(pd.to_datetime(h.Date).min() for h in histories.values())
    end = max(pd.to_datetime(h.Date).max() for h in histories.values())
    sessions = session_calendar(start, end + pd.Timedelta(days=250))
    past_sessions = sessions[sessions <= end]
    evaluation_start = past_sessions[max(0, len(past_sessions) - args.evaluation_sessions)]
    source_paths = [args.history_file, args.history_file.parent/'manifest.json'] if args.history_file else [
        DATA_DIR/'oslo_stock_exchange_all_companies.xlsx', DATA_DIR/'oslo_actual_prices.csv']
    source_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths if p.exists()}
    metadata = dict(version=VERSION, code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    sources=source_hashes, price_basis=price_basis, history_file=str(args.history_file.resolve()) if args.history_file else None, as_of=args.as_of, evaluation_start=str(evaluation_start.date()),
                    min_train=args.min_train, window=args.window, min_feedback=args.min_feedback,
                    tickers=sorted(histories), horizons=HORIZONS, calendar='XOSL',
                    calendar_version=xcals.__version__, decision_time='after close',
                    provenance='reconstructed_backtest',
                    limitation='Retrospective provider-adjusted feed; not point-in-time. Provider checks do not verify all corporate actions. Survivor/validation-selected universe; overlapping outcomes.')
    experiment_id = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()[:20]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    db = open_archive(args.archive)
    db.execute('INSERT OR IGNORE INTO experiments VALUES (?,?,?)',
               (experiment_id, datetime.now(timezone.utc).isoformat(), json.dumps(metadata, sort_keys=True)))
    db.commit()
    # Adjusted snapshots can revise historical scales after future actions.
    # Never attach their prices to old forecasts from another basis or snapshot.
    legacy_experiments = {row[0] for row in db.execute('SELECT experiment_id,metadata FROM experiments')
                          if json.loads(row[1]).get('price_basis', 'legacy_unverified') == 'legacy_unverified'}
    resolved_earlier = (resolve_archived_outcomes(db, histories, args.as_of, legacy_experiments)
                        if not args.history_file else 0)
    imported = import_legacy(db, DATA_DIR)
    ticker_summaries = []
    counts = {s:0 for s in ('resolved','pending','missing_actual')}
    quality = []
    for index, (ticker, history) in enumerate(sorted(histories.items()), 1):
        rows = list(evaluate(ticker, history, args.min_train, sessions=sessions,
                            evaluation_start=evaluation_start, window=args.window, min_feedback=args.min_feedback, as_of=args.as_of))
        if not rows:
            continue
        archive_rows(db, experiment_id, rows)
        frame = pd.DataFrame(rows)
        ticker_summaries.append(summaries(frame, ['ticker','horizon_days','model']))
        for status, count in frame.status.value_counts().items(): counts[status] += int(count)
        series = clean_history(history)
        jumps = series.pct_change(fill_method=None).abs() > .4
        for day in series.index[jumps]:
            quality.append({'ticker':ticker, 'date':str(day.date()), 'issue':'absolute one-observation price change > 40%; inspect corporate actions / source consistency'})
        if index % 25 == 0: print(f'Processed {index}/{len(histories)} tickers', flush=True)
    if not ticker_summaries:
        raise SystemExit('No evaluable predictions')
    detail = pd.concat(ticker_summaries, ignore_index=True)
    detail.to_csv(args.output_dir/'per_ticker_metrics.csv', index=False)
    # Pool sufficient statistics; also expose equal-ticker MAE so large histories do not dominate silently.
    pooled = []
    for (horizon, model), group in detail.groupby(['horizon_days','model']):
        weights = group.observations
        pooled.append(dict(horizon_days=int(horizon), model=model, observations=int(weights.sum()),
                           tickers=len(group), mae_log_return_pct=np.average(group.mae_log_return_pct, weights=weights),
                           rmse_log_return_pct=np.sqrt(np.average(group.rmse_log_return_pct**2, weights=weights)),
                           bias_log_return_pct=np.average(group.bias_log_return_pct, weights=weights),
                           directional_accuracy=np.average(group.directional_accuracy, weights=weights),
                           equal_ticker_mae_log_return_pct=group.mae_log_return_pct.mean()))
    summary = pd.DataFrame(pooled, columns=["horizon_days","model","observations","tickers","mae_log_return_pct","rmse_log_return_pct","bias_log_return_pct","directional_accuracy","equal_ticker_mae_log_return_pct"])
    summary.to_csv(args.output_dir/'summary.csv', index=False)
    pd.DataFrame(quality, columns=['ticker','date','issue']).to_csv(args.output_dir/'data_quality_flags.csv', index=False)
    metadata.update(experiment_id=experiment_id, archive=str(args.archive.resolve()), counts=counts,
                    legacy_rows_added=imported, earlier_outcomes_resolved=resolved_earlier, quality_flags=len(quality))
    (args.output_dir/'run_metadata.json').write_text(json.dumps(metadata, indent=2))
    print(summary.pivot(index='horizon_days', columns='model', values='mae_log_return_pct').round(3).to_string())
    print(f'Experiment: {experiment_id}; row statuses: {counts}; quality flags: {len(quality)}')
    db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ticker')
    parser.add_argument('--history-file', type=Path, help='Checksum-validated prices.csv from repair_history.py')
    parser.add_argument('--price-basis', choices=['close', 'adjusted_close'], default='adjusted_close')
    parser.add_argument('--as-of', default=datetime.now(timezone.utc).date().isoformat())
    parser.add_argument('--min-train', type=int, default=120)
    parser.add_argument('--evaluation-sessions', type=int, default=252)
    parser.add_argument('--window', type=int, default=60)
    parser.add_argument('--min-feedback', type=int, default=20)
    parser.add_argument('--archive', type=Path, default=DATA_DIR/'forecast_outcomes.sqlite')
    parser.add_argument('--output-dir', type=Path, default=DATA_DIR/'adaptive_backtest')
    main(parser.parse_args())
