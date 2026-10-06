import sys
from pathlib import Path
import sqlite3
import tempfile
import unittest

import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'forecasting'))
import walk_forward_backtest as backtest


class BacktestTests(unittest.TestCase):
    def setUp(self):
        self.sessions = pd.bdate_range('2023-01-02', periods=420)
        self.history = pd.DataFrame({'Date':self.sessions[:300],
                                    'Close':100*np.exp(np.arange(300)*.001 + np.sin(np.arange(300))*.005)})

    def rows(self, history=None):
        return list(backtest.evaluate('TEST', self.history if history is None else history,
                                     sessions=self.sessions, min_train=120))

    def test_future_changes_cannot_change_past_predictions(self):
        changed = self.history.copy()
        changed.loc[changed.index > 220, 'Close'] *= 2
        original, altered = self.rows(), self.rows(changed)
        keys = ['origin_date','target_date','horizon_days','model','predicted_log_return','feedback_count','weights']
        before = lambda rows: [[r[k] for k in keys] for r in rows if r['origin_date'] <= str(self.sessions[220].date())]
        self.assertEqual(before(original), before(altered))

    def test_feedback_only_matures_at_target_close(self):
        rows = self.rows()
        selected = {(r['origin_date'],r['horizon_days']):r for r in rows if r['model']=='adaptive_ensemble'}
        self.assertEqual(selected[(str(self.sessions[219].date()),100)]['feedback_count'],0)
        self.assertEqual(selected[(str(self.sessions[220].date()),100)]['feedback_count'],1)
        self.assertEqual(selected[(str(self.sessions[139].date()),1)]['feedback_count'],19)
        self.assertEqual(selected[(str(self.sessions[140].date()),1)]['feedback_count'],20)

    def test_includes_origin_close_in_features(self):
        row = next(r for r in self.rows() if r['model']=='momentum_5' and r['horizon_days']==1)
        prices = self.history.Close.to_numpy()
        self.assertAlmostEqual(row['predicted_log_return'], np.log(prices[120]/prices[115])/5)

    def test_missing_quote_does_not_shift_target(self):
        changed = self.history.drop(index=140)
        row = next(r for r in self.rows(changed) if r['origin_date']==str(self.sessions[120].date()) and r['horizon_days']==20)
        self.assertEqual(row['target_date'],str(self.sessions[140].date()))
        self.assertEqual(row['status'],'missing_actual')
        self.assertIsNone(row['actual_price'])

    def test_all_horizons_and_pending_forecasts(self):
        rows = self.rows()
        self.assertEqual({r['horizon_days'] for r in rows},{1,5,20,30,60,100})
        self.assertTrue(any(r['status']=='pending' for r in rows))
        self.assertTrue(all(r['actual_price'] is None for r in rows if r['status']=='pending'))

    def test_archive_idempotent_and_prediction_immutable(self):
        with tempfile.TemporaryDirectory() as folder:
            db = backtest.open_archive(Path(folder)/'archive.sqlite')
            db.execute("INSERT INTO experiments VALUES ('test','now','{}')")
            row = self.rows()[0]
            backtest.archive_rows(db,'test',[row])
            altered = dict(row, predicted_price=999)
            backtest.archive_rows(db,'test',[altered])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM forecasts').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT predicted_price FROM forecasts').fetchone()[0],row['predicted_price'])
            db.close()

    def test_as_of_truncates_future_observations(self):
        cutoff = str(self.sessions[200].date())
        rows = list(backtest.evaluate('TEST', self.history, sessions=self.sessions, as_of=cutoff))
        self.assertTrue(all(r['origin_date'] <= cutoff for r in rows))
        self.assertTrue(all(r['actual_price'] is None for r in rows if r['target_date'] > cutoff))

    def test_pending_archive_resolves_without_rewriting_forecast(self):
        with tempfile.TemporaryDirectory() as folder:
            db = backtest.open_archive(Path(folder)/'archive.sqlite')
            db.execute("INSERT INTO experiments VALUES ('test','now','{}')")
            row = next(r for r in backtest.evaluate('TEST', self.history.iloc[:201], sessions=self.sessions)
                       if r['origin_date']==str(self.sessions[200].date()) and r['horizon_days']==1)
            self.assertEqual(row['status'],'pending')
            backtest.archive_rows(db,'test',[row])
            backtest.resolve_archived_outcomes(db, {'TEST':self.history}, str(self.sessions[201].date()))
            self.assertEqual(db.execute('SELECT status FROM outcomes').fetchone()[0],'resolved')
            self.assertEqual(db.execute('SELECT predicted_price FROM forecasts').fetchone()[0],row['predicted_price'])
            db.close()

    def test_resolution_does_not_cross_price_bases(self):
        with tempfile.TemporaryDirectory() as folder:
            db = backtest.open_archive(Path(folder)/'archive.sqlite')
            db.execute("INSERT INTO experiments VALUES ('legacy','now','{}')")
            row = next(r for r in backtest.evaluate('TEST', self.history.iloc[:201], sessions=self.sessions)
                       if r['origin_date']==str(self.sessions[200].date()) and r['horizon_days']==1)
            backtest.archive_rows(db,'legacy',[row])
            backtest.resolve_archived_outcomes(db, {'TEST':self.history}, str(self.sessions[201].date()), compatible_experiments=set())
            self.assertEqual(db.execute('SELECT status FROM outcomes').fetchone()[0],'pending')
            db.close()

    def test_oslo_calendar_excludes_weekends_and_holiday(self):
        sessions = backtest.session_calendar('2026-03-30','2026-04-10')
        self.assertNotIn(pd.Timestamp('2026-04-03'), sessions)
        self.assertNotIn(pd.Timestamp('2026-04-06'), sessions)
        self.assertNotIn(pd.Timestamp('2026-04-04'), sessions)


if __name__ == '__main__': unittest.main()
