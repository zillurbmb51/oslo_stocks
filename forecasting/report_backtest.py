#!/usr/bin/env python3
"""Export readable coverage and non-overlapping checks from a completed experiment."""
import argparse
import json
from pathlib import Path
import sqlite3

import numpy as np
import pandas as pd

from walk_forward_backtest import session_calendar


def main(output):
    metadata = json.loads((output/'run_metadata.json').read_text())
    db = sqlite3.connect(metadata['archive'])
    experiment = metadata['experiment_id']
    coverage = pd.read_sql_query('''SELECT f.ticker,f.horizon_days,
        MIN(f.origin_date) first_origin,MAX(f.origin_date) last_origin,
        MIN(CASE WHEN o.status='resolved' THEN f.target_date END) first_observed_target,
        MAX(CASE WHEN o.status='resolved' THEN f.target_date END) last_observed_target,
        COUNT(*) forecasts,
        SUM(o.status='resolved') resolved, SUM(o.status='pending') pending,
        SUM(o.status='missing_actual') missing_actual,
        SUM(f.feedback_count >= ?) adapted_forecasts
        FROM forecasts f JOIN outcomes o USING(experiment_id,ticker,origin_date,horizon_days,model)
        WHERE f.experiment_id=? AND f.model='adaptive_ensemble'
        GROUP BY f.ticker,f.horizon_days''', db, params=(metadata['min_feedback'],experiment))
    coverage.to_csv(output/'coverage.csv',index=False)
    latest = pd.read_sql_query('''SELECT f.*,o.actual_price,o.actual_log_return,o.status
        FROM forecasts f JOIN outcomes o USING(experiment_id,ticker,origin_date,horizon_days,model)
        WHERE f.experiment_id=? AND f.model='adaptive_ensemble' ''',db,params=(experiment,))
    latest = latest.sort_values('origin_date').groupby(['ticker','horizon_days']).tail(1)
    latest.to_csv(output/'latest_archived_ensemble.csv',index=False)
    # One fixed phase anchored at evaluation_start. No selection of the best phase.
    sessions = session_calendar(metadata['evaluation_start'], metadata['as_of'])
    positions = {str(date.date()):i for i,date in enumerate(sessions)}
    checks = []
    for horizon in metadata['horizons']:
        frame = pd.read_sql_query('''SELECT f.ticker,f.origin_date,f.model,
            f.predicted_log_return,o.actual_log_return FROM forecasts f JOIN outcomes o
            USING(experiment_id,ticker,origin_date,horizon_days,model)
            WHERE f.experiment_id=? AND f.horizon_days=? AND o.status='resolved' ''',
            db,params=(experiment,horizon))
        frame = frame[frame.origin_date.map(positions).mod(horizon).eq(0)]
        for model, group in frame.groupby('model'):
            errors = (group.predicted_log_return-group.actual_log_return)*100
            checks.append(dict(horizon_days=horizon,model=model,observations=len(group),
                               mae_log_return_pct=errors.abs().mean(),rmse_log_return_pct=np.sqrt((errors**2).mean())))
    pd.DataFrame(checks).to_csv(output/'nonoverlapping_metrics.csv',index=False)
    metrics = pd.read_csv(output/'summary.csv')
    pivot = metrics.pivot(index='horizon_days',columns='model',values='mae_log_return_pct')
    comparison = pivot[['no_change','adaptive_ensemble']].copy()
    comparison['adaptive_error_change_pct'] = (comparison.adaptive_ensemble / comparison.no_change - 1)*100
    comparison.to_csv(output/'comparison.csv')
    lines = [f'Experiment {experiment}',
             f'Data cutoff: {metadata["as_of"]}',
             f'Price basis: {metadata.get("price_basis", "legacy_unverified")}',
             f'Forecast origins actually generated: {coverage.first_origin.min()} to {coverage.last_origin.max()}',
             f'Tickers with forecasts: {coverage.ticker.nunique()}',
             f'Unique ticker/origin/horizon forecasts: {int(coverage.forecasts.sum())}',
             f'Resolved: {int(coverage.resolved.sum())}; missing actual: {int(coverage.missing_actual.sum())}; pending: {int(coverage.pending.sum())}',
             '', 'MAE in percentage points of log return; lower is better:', comparison.round(3).to_string(),
             '', 'Positive error change means the adaptive ensemble is worse than no-change.',
             ('Adaptive MAE is not lower than no-change at any tested horizon.'
              if (comparison.adaptive_ensemble >= comparison.no_change).all()
              else 'Some horizons have lower adaptive MAE; inspect coverage and robustness before drawing conclusions.'),
             'The latest available prices may be newer than the last eligible origin:',
             'missing sessions prevent the required 61 consecutive-session input window.',
             'Legacy forecasts have unverified timing and are excluded from these scores.',
             'Non-overlapping metrics use one fixed phase; no significance or trading-profit claim.',
             'Inspect data_quality_flags.csv for source/corporate-action discontinuities.']
    (output/'RESULTS.txt').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines))
    db.close()


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=Path(__file__).resolve().parents[1]/'data'/'adaptive_backtest')
    main(parser.parse_args().output_dir)
