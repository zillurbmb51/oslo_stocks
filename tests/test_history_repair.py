import sys
import json
import tempfile
from pathlib import Path
import unittest
import pandas as pd
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'forecasting'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from repair_history import audit_history, completed_cutoff, load_validated_history, sha256
from app.update_actual_prices import parse_actual_rows, parse_price


class HistoryRepairTests(unittest.TestCase):
    def setUp(self):
        self.sessions=pd.bdate_range('2026-01-05',periods=4)
        self.f=pd.DataFrame({'date':self.sessions,'Close':[100.,99.,100.,101.],
            'Adj Close':[99.,99.,100.,101.],'Dividends':[0.,1.,0.,0.],
            'Stock Splits':[0.]*4,'Volume':[100]*4})
        self.meta={'symbol':'TEST.OL','exchangeName':'OSL','currency':'NOK','instrumentType':'EQUITY'}
        self.legacy=pd.DataFrame({'Date':self.sessions,'Close':[100,99,100,101]})
    def audit(self,f=None,meta=None,refs=None):
        return audit_history('TEST',self.f if f is None else f,self.meta if meta is None else meta,self.sessions,self.legacy,refs)
    def test_valid_dividend_factor(self):
        output,issues,actions,_=self.audit()
        self.assertTrue(output.validation.eq('provider_consistent').all())
        self.assertEqual(actions[0]['check'],'consistent')
        self.assertFalse(issues)
    def test_missing_dividend_adjustment_quarantined(self):
        f=self.f.copy();f['Adj Close']=f.Close
        output,issues,_,_=self.audit(f)
        self.assertTrue(output.validation.eq('quarantined').all())
        self.assertIn('adjustment_factor_mismatch',[i['issue'] for i in issues])
    def test_already_adjusted_split_not_applied_twice(self):
        f=self.f.copy();f['Dividends']=0;f['Adj Close']=f.Close;f.loc[1,'Stock Splits']=2
        output,issues,_,_=self.audit(f)
        self.assertEqual(output.close.iloc[0],100)
        self.assertFalse(any(i['severity']=='block' for i in issues))
    def test_unadjusted_split_quarantined(self):
        f=self.f.copy();f['Dividends']=0;f['Close']=[100,50,51,52];f['Adj Close']=f.Close;f.loc[1,'Stock Splits']=2
        _,issues,_,_=self.audit(f)
        self.assertIn('possible_unadjusted_split',[i['issue'] for i in issues])
    def test_no_forward_fill_missing_session(self):
        f=self.f.drop(index=2)
        output,_,_,_=self.audit(f)
        self.assertNotIn('2026-01-07',output.date.tolist())
    def test_currency_mismatch_and_complex_event_block(self):
        output,_,_,_=self.audit(meta=dict(self.meta,currency='USD'))
        self.assertTrue(output.validation.eq('quarantined').all())
        refs=[dict(ticker='TEST',date='2026-01-07',handling='quarantine',description='Spin off',source_url='https://example.com')]
        _,issues,_,_=self.audit(refs=refs)
        self.assertIn('complex_corporate_action',[i['issue'] for i in issues])
    def test_current_session_excluded_until_final(self):
        self.assertEqual(completed_cutoff('2026-10-06','2026-10-06T10:00:00Z'),'2026-10-05')
    def test_checksum_prevents_silent_history_edits(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'prices.csv';self.audit()[0].to_csv(path,index=False)
            (path.parent/'manifest.json').write_text(json.dumps({'prices_sha256':sha256(path)}))
            self.assertIn('TEST',load_validated_history(path))
            path.write_text(path.read_text()+'\n')
            with self.assertRaises(ValueError):load_validated_history(path)
    def test_updater_uses_explicit_close_date(self):
        text='Symbol;Closing Price;Closing Price DateTime;Currency\nTEST;123.4;05/10/2026 16:30;NOK\n'
        rows,rejected=parse_actual_rows(text,'2026-10-06',now='2026-10-06T18:00:00Z')
        self.assertFalse(rejected);self.assertEqual(rows[0].date,'2026-10-05')
    def test_undated_quote_is_rejected(self):
        text='Symbol;Closing Price;Closing Price DateTime;Currency\nTEST;123.4;;NOK\n'
        rows,rejected=parse_actual_rows(text,'2026-10-06',now='2026-10-06T18:00:00Z')
        self.assertFalse(rows);self.assertEqual(rejected[0]['reason'],'missing_explicit_closing_date')
    def test_weekend_and_unfinished_closes_rejected(self):
        header='Symbol;Closing Price;Closing Price DateTime;Currency\n'
        rows,rejected=parse_actual_rows(header+'TEST;123.4;04/10/2026;NOK\n','2026-10-06',now='2026-10-06T18:00:00Z')
        self.assertFalse(rows);self.assertEqual(rejected[0]['reason'],'not_exchange_session')
        rows,rejected=parse_actual_rows(header+'TEST;123.4;06/10/2026;NOK\n','2026-10-06',now='2026-10-06T10:00:00Z')
        self.assertFalse(rows);self.assertEqual(rejected[0]['reason'],'session_not_final')

    def test_price_formats(self):
        self.assertEqual(parse_price('1,234.56'),1234.56)
        self.assertEqual(parse_price('1.234,56'),1234.56)
        self.assertIsNone(parse_price('-1'))


if __name__=='__main__': unittest.main()
