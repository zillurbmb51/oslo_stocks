#!/usr/bin/env python3
"""Download session-dated histories; audit actions; publish a separate validated snapshot.

No interpolation, no heuristic split inference, and no changes to legacy files.
Provider consistency checks do not constitute independent exchange verification.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import exchange_calendars as xcals
import numpy as np
import pandas as pd

from utils import DATA_DIR, load_all_history

VERSION = 'history-repair-v1'
PRICE_COLUMNS = ['ticker','date','close','adjusted_close','adjustment_factor','dividend','split','volume','currency','validation']
ISSUE_COLUMNS = ['ticker','date','severity','issue','detail']
ACTION_COLUMNS = ['ticker','date','dividend','split','factor_before','factor_after','expected_factor_change','observed_factor_change','check','reference_url']


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def calendar(start, end):
    return xcals.get_calendar('XOSL', start=start, end=end)


def completed_cutoff(requested, now=None):
    """Never ingest an in-progress daily bar, including early-close sessions."""
    now = pd.Timestamp(now or datetime.now(timezone.utc))
    if now.tzinfo is None:
        raise ValueError('now must include a timezone')
    requested = pd.Timestamp(requested).normalize().tz_localize(None)
    today = now.tz_convert('Europe/Oslo').tz_localize(None).normalize()
    end = min(requested, today)
    cal = calendar(end - pd.Timedelta(days=14), end)
    eligible = [day for day in cal.sessions if cal.session_close(day) <= now - pd.Timedelta(minutes=30)]
    if not eligible:
        raise ValueError('No completed session before requested cutoff')
    return pd.Timestamp(eligible[-1]).tz_localize(None).date().isoformat()


def fetch_history(ticker, start, end, raw_dir):
    import yfinance as yf
    symbol = ticker + '.OL'
    table_path, meta_path = raw_dir/f'{ticker}.csv', raw_dir/f'{ticker}.json'
    if table_path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text())
        if meta.get('csv_sha256') != sha256(table_path):
            raise ValueError('Cached provider snapshot checksum mismatch')
        return pd.read_csv(table_path), meta
    stock = yf.Ticker(symbol)
    frame = stock.history(start=start, end=str((pd.Timestamp(end)+pd.Timedelta(days=1)).date()),
                          interval='1d', auto_adjust=False, back_adjust=False,
                          actions=True, repair=False, keepna=True, timeout=20)
    if frame.empty:
        raise ValueError('Provider returned no price history')
    # Preserve the exchange-local session date, not the UTC calendar date.
    dates = frame.index.tz_convert('Europe/Oslo').tz_localize(None) if frame.index.tz is not None else frame.index
    frame = frame.copy()
    frame.index = dates.normalize()
    frame.index.name = 'date'
    frame = frame.reset_index()
    metadata = dict(stock.history_metadata)
    meta = {key:metadata.get(key) for key in ['symbol','currency','exchangeName','instrumentType','exchangeTimezoneName']}
    meta.update(source='Yahoo Finance via yfinance', yfinance_version=yf.__version__,
                retrieved_at=datetime.now(timezone.utc).isoformat(), start=start, end=end,
                auto_adjust=False, repair=False, price_basis='vendor Close (split-adjusted); Adj Close (split and dividend adjusted)')
    raw_dir.mkdir(parents=True, exist_ok=True)
    frame.to_csv(table_path,index=False)
    meta['csv_sha256'] = sha256(table_path)
    meta_path.write_text(json.dumps(meta,indent=2,default=str))
    return frame, meta


def audit_history(ticker, frame, metadata, sessions, legacy, references=None):
    """Check dividend factor identities and split continuity without applying a split twice."""
    issues, action_rows = [], []
    references = references or []
    def issue(date, severity, kind, detail):
        issues.append(dict(ticker=ticker,date=str(date),severity=severity,issue=kind,detail=str(detail)))
    expected_symbol = ticker + '.OL'
    if metadata.get('symbol') != expected_symbol or metadata.get('exchangeName') != 'OSL' or metadata.get('currency') != 'NOK' or metadata.get('instrumentType') != 'EQUITY':
        issue('', 'block', 'identity_or_currency_mismatch', json.dumps(metadata,default=str))
    required = ['date','Close','Adj Close','Dividends','Stock Splits','Volume']
    if any(column not in frame for column in required):
        issue('', 'block', 'missing_provider_columns', ','.join(required))
        return pd.DataFrame(columns=PRICE_COLUMNS), issues, [], []
    f = frame.copy()
    f['date'] = pd.to_datetime(f.date,errors='coerce').dt.tz_localize(None).dt.normalize()
    for column in required[1:]: f[column] = pd.to_numeric(f[column],errors='coerce')
    if f.date.duplicated().any():
        issue('', 'block', 'duplicate_provider_session', 'Duplicate dates require manual review')
    f = f.drop_duplicates('date',keep='last').sort_values('date').set_index('date')
    for day in f.index[~f.index.isin(sessions)]:
        issue(day, 'exclude_row', 'non_session_or_outside_window', 'Not an eligible completed XOSL session')
    f = f[f.index.isin(sessions)]
    finite = np.isfinite(f[required[1:]]).all(axis=1)
    valid = finite & (f.Close>0) & (f['Adj Close']>0) & (f.Volume>=0) & (f.Dividends>=0) & (f['Stock Splits']>=0)
    for day in f.index[~valid]: issue(day,'exclude_row','invalid_provider_values','Nonfinite/nonpositive price or invalid action/volume')
    f = f.loc[valid]
    aligned = f.reindex(sessions)
    factors = aligned['Adj Close']/aligned.Close
    previous_close = aligned.Close.shift()
    expected_change = 1/(1-aligned.Dividends/previous_close)
    observed_change = factors/factors.shift()
    residual = (observed_change/expected_change-1).abs()
    for day in f.index:
        dividend, split = float(f.loc[day,'Dividends']), float(f.loc[day,'Stock Splits'])
        event_references = [ref for ref in references if ref['ticker']==ticker and ref['date']==str(day.date())]
        for ref in event_references:
            if ref.get('handling') == 'quarantine':
                issue(day,'block','complex_corporate_action',ref['description']+' '+ref['source_url'])
        observed, expected = observed_change.loc[day], expected_change.loc[day]
        state = 'consistent' if np.isfinite(residual.loc[day]) and residual.loc[day] <= .005 else 'unverifiable'
        if np.isfinite(residual.loc[day]) and residual.loc[day] > .005:
            issue(day,'block','adjustment_factor_mismatch',f'Expected multiplier {expected}; observed {observed}')
            state = 'mismatch'
        if dividend > 0 and (not np.isfinite(expected) or expected <= 0):
            issue(day,'block','dividend_not_verifiable','Missing prior session close or dividend >= prior close')
        close_ratio = aligned.Close.loc[day]/previous_close.loc[day]
        if split and split != 1 and np.isfinite(close_ratio) and abs(np.log(close_ratio)) > .25 and np.isclose(close_ratio,1/split,rtol=.15):
            issue(day,'block','possible_unadjusted_split',f'Close ratio {close_ratio}; split ratio {split}; no automatic multiplication applied')
            state = 'possible_unadjusted_split'
        if dividend or split or event_references:
            action_rows.append(dict(ticker=ticker,date=str(day.date()),dividend=dividend,split=split,
                factor_before=factors.shift().loc[day],factor_after=factors.loc[day],
                expected_factor_change=expected,observed_factor_change=observed,check=state,
                reference_url=' | '.join(ref['source_url'] for ref in event_references)))
    returns = aligned['Adj Close'].pct_change(fill_method=None)
    for day in returns.index[returns.abs()>.4]:
        issue(day,'block','large_adjusted_return',f'{returns.loc[day]:.4%}; requires review, not an inferred adjustment')
    # Flag known complex events even when the provider omitted that session entirely.
    for ref in references:
        if ref['ticker']==ticker and ref.get('handling')=='quarantine' and pd.Timestamp(ref['date']) in sessions and pd.Timestamp(ref['date']) not in f.index:
            issue(ref['date'],'block','complex_corporate_action',ref['description']+' '+ref['source_url'])
    legacy = legacy.copy()
    legacy['Date'] = pd.to_datetime(legacy.Date).dt.normalize()
    old = legacy.drop_duplicates('Date',keep='last').set_index('Date').Close
    for day in old.index[(old.index>=sessions[0]) & (old.index<=sessions[-1]) & ~old.index.isin(sessions)]:
        issue(day,'legacy_only','legacy_non_session','Download-date quote must not be treated as a session close')
    overlap = pd.concat([old.rename('legacy_price'), f.Close.rename('provider_close'),f['Adj Close'].rename('provider_adjusted')],axis=1).dropna()
    comparisons = []
    for day, row in overlap.iterrows():
        if day not in sessions: continue
        error_close=abs(row.legacy_price/row.provider_close-1)
        error_adjusted=abs(row.legacy_price/row.provider_adjusted-1)
        if min(error_close,error_adjusted)>.01:
            comparisons.append(dict(ticker=ticker,date=str(day.date()),legacy_price=row.legacy_price,
                provider_close=row.provider_close,provider_adjusted=row.provider_adjusted,
                smallest_relative_difference=min(error_close,error_adjusted)))
    blocked = any(i['severity']=='block' for i in issues)
    output = pd.DataFrame(dict(ticker=ticker,date=f.index.strftime('%Y-%m-%d'),close=f.Close.to_numpy(),
        adjusted_close=f['Adj Close'].to_numpy(),adjustment_factor=(f['Adj Close']/f.Close).to_numpy(),
        dividend=f.Dividends.to_numpy(),split=f['Stock Splits'].to_numpy(),volume=f.Volume.to_numpy(),
        currency='NOK',validation='quarantined' if blocked else 'provider_consistent'))
    return output, issues, action_rows, comparisons


def load_validated_history(path, price_basis='adjusted_close'):
    """Explicit opt-in; never blend adjusted history with the legacy quote CSV."""
    if price_basis not in ('close','adjusted_close'): raise ValueError('Unsupported price basis')
    path = Path(path)
    manifest = json.loads((path.parent/'manifest.json').read_text())
    if manifest.get('prices_sha256') != sha256(path): raise ValueError('Validated history checksum mismatch')
    f = pd.read_csv(path,dtype={'ticker':str},parse_dates=['date'])
    if f.empty or not f.validation.eq('provider_consistent').all(): raise ValueError('No validated data or quarantined rows present')
    if f.duplicated(['ticker','date']).any(): raise ValueError('Duplicate ticker/session')
    if not (np.isfinite(f[price_basis]) & (f[price_basis]>0)).all(): raise ValueError('Invalid validated price')
    return {ticker:g[['date',price_basis]].rename(columns={'date':'Date',price_basis:'Close'}).reset_index(drop=True)
            for ticker,g in f.sort_values('date').groupby('ticker')}


def main(args):
    import yfinance as yf
    if args.workers < 1 or args.workers > 8: raise SystemExit('workers must be 1..8')
    cutoff = completed_cutoff(args.as_of)
    if pd.Timestamp(args.start)>pd.Timestamp(cutoff): raise SystemExit('Start must precede completed cutoff')
    histories=load_all_history()
    if args.tickers:
        names=[t.strip().upper() for t in args.tickers.split(',')]
        histories={t:histories[t] for t in names}
    sessions=calendar(args.start,cutoff).sessions.tz_localize(None)
    sources={p.name:sha256(p) for p in [DATA_DIR/'oslo_actual_prices.csv',DATA_DIR/'oslo_stock_exchange_all_companies.xlsx'] if p.exists()}
    config=dict(version=VERSION,start=args.start,cutoff=cutoff,tickers=sorted(histories),legacy_sources=sources)
    run_dir=args.resume or DATA_DIR/'history_repair'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    run_dir.mkdir(parents=True,exist_ok=True)
    if (run_dir/'manifest.json').exists():
        raise SystemExit('Completed snapshots are immutable; start a new run instead of resuming this one')
    config_path=run_dir/'config.json'
    if config_path.exists() and json.loads(config_path.read_text())!=config: raise SystemExit('Resume configuration differs; start a new snapshot')
    config_path.write_text(json.dumps(config,indent=2))
    yf.set_tz_cache_location(str(run_dir/'provider_cache'))
    reference_path=DATA_DIR/'corporate_action_references.json'
    references=json.loads(reference_path.read_text()) if reference_path.exists() else []
    raw=run_dir/'raw'; raw.mkdir(exist_ok=True)
    outputs,issues,actions,comparisons,coverage,gaps=[],[],[],[],[],[]
    def fetch(ticker):
        error=None
        for attempt in range(2):
            try: return fetch_history(ticker,args.start,cutoff,raw)
            except Exception as exc:
                error=str(exc)
                if attempt==0: time.sleep(1)
        raise ValueError(error)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs={pool.submit(fetch,t):t for t in histories}
        for n,future in enumerate(as_completed(jobs),1):
            ticker=jobs[future]; legacy=histories[ticker]
            first=max(pd.Timestamp(args.start),pd.to_datetime(legacy.Date).min().normalize())
            expected=sessions[sessions>=first]
            old_dates=pd.DatetimeIndex(pd.to_datetime(legacy.Date).dt.normalize())
            old_missing=expected.difference(old_dates)
            try:
                frame,meta=future.result()
                output,found,event_rows,differences=audit_history(ticker,frame,meta,sessions,legacy,references)
                issues.extend(found);actions.extend(event_rows);comparisons.extend(differences)
                accepted=not output.empty and output.validation.eq('provider_consistent').all()
                status='accepted' if accepted else 'quarantined'
                provider_dates=pd.DatetimeIndex(pd.to_datetime(output.date))
                if accepted: outputs.append(output)
            except Exception as exc:
                status='fetch_failed';provider_dates=pd.DatetimeIndex([])
                issues.append(dict(ticker=ticker,date='',severity='block',issue='fetch_failed',detail=str(exc)))
            accepted_dates=provider_dates if status=='accepted' else pd.DatetimeIndex([])
            remaining=expected.difference(accepted_dates)
            recovered=old_missing.intersection(accepted_dates)
            for day in old_missing:
                gaps.append(dict(ticker=ticker,date=str(day.date()),status='recovered' if day in recovered else status if status!='accepted' else 'provider_missing'))
            coverage.append(dict(ticker=ticker,status=status,expected_sessions=len(expected),legacy_missing=len(old_missing),
                recovered_sessions=len(recovered),remaining_missing=len(remaining),provider_rows=len(provider_dates),
                accepted_rows=len(accepted_dates),last_accepted_date=str(accepted_dates.max().date()) if len(accepted_dates) else ''))
            if n%10==0: print(f'Audited {n}/{len(histories)}; accepted {len(outputs)}',flush=True)
    prices=pd.concat(outputs,ignore_index=True) if outputs else pd.DataFrame(columns=PRICE_COLUMNS)
    prices.sort_values(['ticker','date']).to_csv(run_dir/'prices.csv',index=False)
    pd.DataFrame(issues,columns=ISSUE_COLUMNS).to_csv(run_dir/'issues.csv',index=False)
    pd.DataFrame(actions,columns=ACTION_COLUMNS).to_csv(run_dir/'actions.csv',index=False)
    pd.DataFrame(coverage).sort_values('ticker').to_csv(run_dir/'coverage.csv',index=False)
    pd.DataFrame(gaps,columns=['ticker','date','status']).to_csv(run_dir/'gaps.csv',index=False)
    pd.DataFrame(comparisons,columns=['ticker','date','legacy_price','provider_close','provider_adjusted','smallest_relative_difference']).to_csv(run_dir/'legacy_disagreements.csv',index=False)
    manifest=dict(config,created_at=datetime.now(timezone.utc).isoformat(),calendar_version=xcals.__version__,
        yfinance_version=yf.__version__,code_sha256=sha256(Path(__file__)),prices_sha256=sha256(run_dir/'prices.csv'),
        references_sha256=sha256(reference_path) if reference_path.exists() else None,
        accepted_tickers=len(outputs),requested_tickers=len(histories),recovered_sessions=sum(c['recovered_sessions'] for c in coverage),
        unresolved_sessions=sum(c['remaining_missing'] for c in coverage),
        raw_snapshots={p.name:sha256(p) for p in sorted(raw.glob('*'))},
        verification='provider identity and arithmetic consistency; not comprehensive independent corporate-action verification',
        warning='Downloaded history is retrospectively adjusted and is not a point-in-time feed. Complex actions require review. No automatic interpolation or repair heuristics.')
    (run_dir/'manifest.json').write_text(json.dumps(manifest,indent=2))
    print(json.dumps({k:manifest[k] for k in ['accepted_tickers','requested_tickers','recovered_sessions','unresolved_sessions']},indent=2))
    print(f'Snapshot: {run_dir}',flush=True)
    if not len(outputs): raise SystemExit('No series passed validation; originals unchanged')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--as-of',required=True)
    parser.add_argument('--start',default='2020-01-01')
    parser.add_argument('--tickers')
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--resume',type=Path)
    main(parser.parse_args())
