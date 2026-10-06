import copy
import gzip
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.market_store import MarketStore, decode_bundle, expected_session


def bundle(cutoff='2026-01-05'):
    return dict(schema_version=1,cutoff=cutoff,generated_at='2026-01-05T18:00:00+00:00',
        series={'TEST':{'dates':[cutoff],'closes':[100.]}},coverage={'TEST':{'status':'accepted'}},
        backtest={'as_of':cutoff,'summary':[]},source='test',price_basis='close',validation='test',schedule_utc='test',counts={'accepted':1})


def encode(value): return gzip.compress(json.dumps(value).encode())


class MarketStoreTests(unittest.TestCase):
    def test_invalid_prices_and_quarantine_rejected(self):
        data=bundle();data['series']['TEST']['closes']=[-1]
        with self.assertRaises(ValueError):decode_bundle(encode(data))
        data=bundle();data['coverage']['TEST']['status']='quarantined'
        with self.assertRaises(ValueError):decode_bundle(encode(data))
    def test_failed_fetch_retains_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'initial.gz';path.write_bytes(encode(bundle()))
            store=MarketStore(path,Path(directory)/'cache.gz')
            old=copy.deepcopy(store.data)
            with patch('app.market_store.urlopen',side_effect=OSError('offline')):store.refresh()
            self.assertEqual(store.data,old);self.assertIsNotNone(store.error)
    def test_cache_survives_restart_and_older_release_cannot_regress(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'initial.gz';path.write_bytes(encode(bundle()))
            cache=Path(directory)/'cache.gz';store=MarketStore(path,cache)
            with patch('app.market_store.urlopen',return_value=io.BytesIO(encode(bundle('2026-01-06')))):store.refresh()
            self.assertEqual(MarketStore(path,cache).data['cutoff'],'2026-01-06')
            with patch('app.market_store.urlopen',return_value=io.BytesIO(encode(bundle()))):store.refresh()
            self.assertEqual(store.data['cutoff'],'2026-01-06')
    def test_weekend_freshness_uses_exchange_calendar(self):
        self.assertEqual(expected_session('2026-10-10T12:00:00Z'),'2026-10-09')
    def test_root_redirect_and_quarantine_do_not_expose_legacy_quotes(self):
        from app import main
        response=main.root();self.assertEqual(response.status_code,307)
        self.assertEqual(response.headers['location'],'/static/index.html')
        with patch.object(main.STORE,'data',bundle()):
            value=main.get_actual('TEST');self.assertEqual(value.prices,[100.])
            self.assertEqual(value.source,'validated_snapshot')
            missing=main.get_actual('UNKNOWN');self.assertEqual(missing.prices,[])
            self.assertEqual(missing.validation_status,'unavailable')
    def test_report_and_price_cutoffs_must_match(self):
        data=bundle();data['backtest']['as_of']='2025-01-01'
        with self.assertRaises(ValueError):decode_bundle(encode(data))


if __name__=='__main__':unittest.main()
