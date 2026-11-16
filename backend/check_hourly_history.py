"""TEST DATA: bounded recovery from an empty Yahoo hourly response."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from backend.interval_history import download, persist, page
from backend.market_store import MarketRecorder


def bars():
    return pd.DataFrame({'Open':[100,102],'High':[103,104],'Low':[99,100],
        'Close':[102,101],'Volume':[1200,850]},index=pd.to_datetime(['2026-11-13T14:30:00Z','2026-11-13T15:30:00Z']))


class HourlyHistoryChecks(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(prefix='hourly-check-')
        self.database=Path(self.directory.name)/'market.db'
        with MarketRecorder(self.database): pass

    def tearDown(self):
        self.directory.cleanup()

    def test_empty_hourly_uses_one_safe_60m_fallback_and_persists(self):
        with patch('backend.interval_history.yf.Ticker') as ticker:
            history=ticker.return_value.history
            history.side_effect=[pd.DataFrame(),bars()]
            result=download(self.database,'AAPL','1h')
            self.assertEqual(result['status'],'ok')
            self.assertEqual(history.call_count,2)
            self.assertEqual([c.kwargs['interval'] for c in history.call_args_list],['1h','60m'])
            self.assertGreaterEqual(history.call_args.kwargs['start'],result['fetched']-timedelta(days=729,seconds=5))
            self.assertEqual(history.call_args.kwargs['timeout'],10)
        persist(self.database,'AAPL','1h',result)
        persist(self.database,'AAPL','1h',result)
        with MarketRecorder(self.database) as store:
            stored=page(store.connection,'AAPL','1h',500)
            self.assertEqual(stored['candles'][-1]['close'],101)
            self.assertEqual(stored['candles'][-1]['volume'],850)
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM interval_revisions').fetchone()[0],2)

    def test_both_empty_stop_after_two_and_keep_saved_data(self):
        with patch('backend.interval_history.yf.Ticker') as ticker:
            ticker.return_value.history.return_value=bars()
            persist(self.database,'AAPL','1h',download(self.database,'AAPL','1h'))
            ticker.return_value.history.reset_mock()
            ticker.return_value.history.return_value=pd.DataFrame()
            failure=download(self.database,'AAPL','1h')
            self.assertEqual(ticker.return_value.history.call_count,2)
        persist(self.database,'AAPL','1h',failure)
        self.assertIn('no price bars',failure['message'])
        self.assertNotIn('ValueError',failure['message'])
        with MarketRecorder(self.database) as store:
            self.assertEqual(len(page(store.connection,'AAPL','1h',500)['candles']),2)

    def test_good_primary_makes_one_request(self):
        with patch('backend.interval_history.yf.Ticker') as ticker:
            ticker.return_value.history.return_value=bars()
            self.assertEqual(download(self.database,'AAPL','1h')['status'],'ok')
            self.assertEqual(ticker.return_value.history.call_count,1)

    def test_request_exception_has_safe_error_and_no_retry_loop(self):
        with patch('backend.interval_history.yf.Ticker') as ticker:
            ticker.return_value.history.side_effect=ConnectionError('TEST DATA private upstream details')
            failure=download(self.database,'AAPL','1h')
            self.assertEqual(ticker.return_value.history.call_count,1)
        self.assertIn('upstream request failed',failure['message'])
        self.assertNotIn('private upstream details',failure['message'])


if __name__=='__main__':
    unittest.main(verbosity=2)
