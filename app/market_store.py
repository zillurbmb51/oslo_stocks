"""Small immutable market snapshots, independently refreshed from a release asset.

Render's local disk is only a disposable cache. The published release is the
persistent source; failed fetches never remove the last good in-memory snapshot.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import gzip
import json
import math
import os
from pathlib import Path
import threading
from urllib.request import Request, urlopen

URL = os.environ.get('MARKET_DATA_URL', 'https://github.com/zillurbmb51/oslo_stocks/releases/download/market-data/latest.json.gz')
BOOTSTRAP = Path(__file__).resolve().parents[1]/'data'/'bootstrap_market.json.gz'
CACHE = Path(os.environ.get('MARKET_CACHE_FILE','/tmp/osl-market-cache.json.gz'))


def decode_bundle(raw):
    if len(raw)>10_000_000: raise ValueError('Market asset too large')
    import io
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        decoded=stream.read(30_000_001)
    if len(decoded)>30_000_000: raise ValueError('Expanded market asset too large')
    data=json.loads(decoded)
    if data.get('schema_version')!=1 or not isinstance(data.get('series'),dict) or not data['series']:
        raise ValueError('Unsupported market snapshot')
    cutoff=datetime.fromisoformat(data['cutoff']).date()
    if cutoff>datetime.now(timezone.utc).date(): raise ValueError('Future market cutoff')
    for ticker,series in data['series'].items():
        dates,closes=series['dates'],series['closes']
        if not dates or len(dates)!=len(closes) or dates!=sorted(set(dates)):
            raise ValueError('Malformed market series')
        if any(datetime.fromisoformat(day).date()>cutoff for day in dates): raise ValueError('Price after cutoff')
        if any(not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in closes):
            raise ValueError('Invalid market price')
        if data['coverage'][ticker]['status']!='accepted': raise ValueError('Quarantined series')
    for ticker, origins in data.get('forecast_comparisons', {}).items():
        series=data['series'].get(ticker)
        if not series or len(series.get('adjusted',[]))!=len(series['dates']):
            raise ValueError('Missing comparison price basis')
        if any(not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in series['adjusted']):
            raise ValueError('Invalid adjusted price')
        prices=dict(zip(series['dates'],series['adjusted']))
        for origin in origins:
            if origin['date'] not in prices or not math.isclose(origin['price'],prices[origin['date']],rel_tol=1e-8):
                raise ValueError('Forecast origin price mismatch')
            horizons=set()
            for horizon,target,value in origin['points']:
                if horizon not in (1,5,20,30,60,100) or horizon in horizons or target<=origin['date']:
                    raise ValueError('Invalid forecast target')
                datetime.fromisoformat(target)
                if not math.isfinite(value) or value<=0: raise ValueError('Invalid forecast value')
                horizons.add(horizon)
    if data.get('backtest',{}).get('as_of')!=data['cutoff']: raise ValueError('Mismatched backtest')
    return data


def expected_session(now=None):
    import exchange_calendars as xcals
    import pandas as pd
    now=pd.Timestamp(now or datetime.now(timezone.utc))
    day=now.tz_convert('Europe/Oslo').date()
    cal=xcals.get_calendar('XOSL',start=day-timedelta(days=14),end=day)
    eligible=[s for s in cal.sessions if cal.session_close(s)+pd.Timedelta(minutes=30)<=now]
    return str(eligible[-1].date()) if eligible else None


class MarketStore:
    def __init__(self, bootstrap=BOOTSTRAP, cache=CACHE):
        self.data=None
        self.origin=None
        self.last_checked=None
        self.error=None
        self.cache=cache
        self.lock=threading.Lock()
        for path,label in [(bootstrap,'bundled snapshot'),(cache,'cached published snapshot')]:
            try:
                candidate=decode_bundle(path.read_bytes())
                if self.data is None or candidate['cutoff']>=self.data['cutoff']:
                    self.data=candidate;self.origin=label
            except (OSError,ValueError,KeyError,TypeError,EOFError):
                pass

    def refresh(self):
        # One worker at a time; readers retain a complete immutable old dict.
        if not self.lock.acquire(blocking=False): return
        try:
            request=Request(URL,headers={'User-Agent':'MyStocks-OSL/2','Cache-Control':'no-cache'})
            with urlopen(request,timeout=30) as response:
                raw=response.read(10_000_001)
            candidate=decode_bundle(raw)
            if self.data and candidate['cutoff']<self.data['cutoff']:
                raise ValueError('Older published snapshot rejected')
            if self.data and len(candidate['series'])<.8*len(self.data['series']):
                raise ValueError('Published coverage dropped unexpectedly')
            self.cache.parent.mkdir(parents=True,exist_ok=True)
            temporary=self.cache.with_suffix('.tmp')
            temporary.write_bytes(raw);temporary.replace(self.cache)
            self.data=candidate
            self.origin='automated published snapshot'
            self.error=None
        except Exception as error:
            self.error=f'{type(error).__name__}: published snapshot unavailable; retaining last good data'
        finally:
            self.last_checked=datetime.now(timezone.utc).isoformat()
            self.lock.release()

    async def poll(self):
        while True:
            await asyncio.to_thread(self.refresh)
            await asyncio.sleep(60 if self.error else 900)

    def status(self,ticker=None):
        data=self.data
        expected=expected_session()
        if not data: return dict(available=False,stale=True,error=self.error,expected_session=expected)
        return dict(available=True,cutoff=data['cutoff'],expected_session=expected,
                    stale=bool(expected and data['cutoff']<expected),origin=self.origin,
                    generated_at=data['generated_at'],last_checked=self.last_checked,error=self.error,
                    source=data['source'],price_basis=data['price_basis'],validation=data['validation'],
                    schedule_utc=data['schedule_utc'],counts=data['counts'],
                    ticker_status=data['coverage'].get(ticker) if ticker else None,
                    backtest=data['backtest'])


STORE=MarketStore()
