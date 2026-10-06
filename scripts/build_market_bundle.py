#!/usr/bin/env python3
"""Publish only validated prices and compact reports, never the SQLite archives."""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import sqlite3
from pathlib import Path

import pandas as pd


def build(snapshot, destination, previous=None):
    manifest=json.loads((snapshot/'manifest.json').read_text())
    if hashlib.sha256((snapshot/'prices.csv').read_bytes()).hexdigest()!=manifest['prices_sha256']:
        raise ValueError('History checksum mismatch')
    prices=pd.read_csv(snapshot/'prices.csv',dtype={'ticker':str})
    coverage=pd.read_csv(snapshot/'coverage.csv',dtype={'ticker':str}).fillna('')
    issues=pd.read_csv(snapshot/'issues.csv',dtype={'ticker':str}).fillna('')
    backtest=json.loads((snapshot/'backtest'/'run_metadata.json').read_text())
    if backtest['sources'].get('prices.csv')!=manifest['prices_sha256']:
        raise ValueError('Backtest does not match the price snapshot')
    if backtest['as_of']!=manifest['cutoff']:
        raise ValueError('Backtest and price cutoffs differ')
    if not prices.validation.eq('provider_consistent').all():
        raise ValueError('Quarantined data cannot be published')
    count=prices.ticker.nunique()
    if count<100: raise ValueError('Fewer than 100 tickers passed; retaining the previous published snapshot')
    latest=prices.groupby('ticker').date.max()
    if (latest==manifest['cutoff']).mean()<.8: raise ValueError('Too many stale closing prices')
    if previous and previous.exists():
        old=json.loads(gzip.decompress(previous.read_bytes()))
        if manifest['cutoff']<old['cutoff'] or count<.8*len(old['series']):
            raise ValueError('Regressing date or coverage; retaining previous snapshot')
    series={ticker:{'dates':g.date.tolist(),'closes':g.close.tolist(),'adjusted':g.adjusted_close.tolist()} for ticker,g in prices.sort_values('date').groupby('ticker')}
    # Keep a compact six-month origin window. Forecast values and observations
    # come from this exact experiment/snapshot, never a later adjustment basis.
    with sqlite3.connect(snapshot/'backtest.sqlite') as db:
        rows=pd.read_sql_query("""SELECT ticker,origin_date,origin_price,horizon_days,
            target_date,predicted_price FROM forecasts WHERE experiment_id=?
            AND model='adaptive_ensemble' ORDER BY ticker,origin_date,horizon_days""",
            db,params=(backtest['experiment_id'],))
    forecasts={}
    for ticker, group in rows.groupby('ticker'):
        origins=sorted(group.origin_date.unique())[-126:]
        forecasts[ticker]=[dict(date=origin,price=float(g.origin_price.iloc[0]),
            points=[[int(r.horizon_days),r.target_date,float(r.predicted_price)]
                    for r in g.itertuples()])
            for origin,g in group[group.origin_date.isin(origins)].groupby('origin_date')]
    statuses={}
    for record in coverage.to_dict('records'):
        ticker=record.pop('ticker')
        record['issues']=sorted(set(issues.loc[(issues.ticker==ticker)&(issues.severity=='block'),'issue']))
        statuses[ticker]=record
    summary=pd.read_csv(snapshot/'backtest'/'summary.csv').to_dict('records')
    data=dict(schema_version=1,generated_at=datetime.now(timezone.utc).isoformat(),cutoff=manifest['cutoff'],
        source='Yahoo Finance via yfinance',price_basis='split-adjusted close, NOK',
        validation='Provider consistency checks; not comprehensive independent action verification',
        forecast_comparisons=forecasts,schedule_utc='17:35 Monday–Friday',series=series,coverage=statuses,
        counts=dict(accepted=count,quarantined=int((coverage.status=='quarantined').sum()),
                    unavailable=int((coverage.status=='fetch_failed').sum()),recovered_sessions=manifest['recovered_sessions']),
        backtest=dict(as_of=backtest['as_of'],price_basis=backtest['price_basis'],
                      experiment_id=backtest['experiment_id'],summary=summary))
    encoded=json.dumps(data,allow_nan=False,separators=(',',':')).encode()
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_bytes(gzip.compress(encoded,mtime=0))
    print(f'Published bundle: {destination}; {count} tickers; {manifest["cutoff"]}; {destination.stat().st_size} bytes')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--previous',type=Path)
    a=p.parse_args();build(a.snapshot,a.output,a.previous)
