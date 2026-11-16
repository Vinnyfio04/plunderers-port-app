"""Focused, offline regressions for chart analysis; disposable SQLite only."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.decisions import DecisionStore, decision_request, review_request, call_decision_provider, validate_provider_input
from backend.indicators import IndicatorStore
from backend.market_store import MarketRecorder
from backend.paper_trading import PaperAccount


def candles(count):
    beginning = datetime(2026, 11, 9, 14, 30, tzinfo=timezone.utc)
    return [dict(timestamp=(beginning + timedelta(minutes=i)).isoformat().replace('+00:00', 'Z'),
                 open=10, high=13, low=8, close=9 if i % 2 else 12, volume=100) for i in range(count)]


class ChartAnalysisChecks(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='chart-analysis-')
        database = Path(self.directory.name) / 'test.db'
        with MarketRecorder(database):
            pass
        self.paper = PaperAccount(database, 1000)
        self.indicators = IndicatorStore(database)
        for window in (1, 2):
            self.indicators.create('AAPL', '1m', f'Test SMA {window}', 'sma', {'window': window})
        self.store = DecisionStore(database, self.indicators, self.paper, Path(self.directory.name) / 'captures')

    def tearDown(self):
        self.store.close()
        self.indicators.close()
        self.paper.close()
        self.directory.cleanup()

    def snapshot(self, rows, completed=True):
        return self.store.create_snapshot('AAPL', '1m', rows[-1]['timestamp'], rows,
            context=dict(candles=rows, status=[dict(timestamp=c['timestamp'], interval_ended=completed) for c in rows]))

    def test_two_hundred_candles_fit_both_role_payloads(self):
        snapshot = self.snapshot(candles(200))
        validate_provider_input(decision_request(snapshot, 'data:image/png;base64,TEST'))
        validate_provider_input(review_request(snapshot, 'data:image/png;base64,TEST', []))
        self.assertEqual(snapshot['chart_range']['candles'], 200)
        self.assertEqual(self.paper.snapshot('AAPL')['orders'], [])

    def test_original_1950_candle_failure_is_rejected_before_network(self):
        snapshot = self.snapshot(candles(2))
        snapshot['candles'] = candles(1950)  # TEST DATA: reproduce the saved HTTP 400 input shape.
        with patch('backend.decisions.urlopen') as transport:
            with self.assertRaisesRegex(ValueError, 'provider evidence limit'):
                call_decision_provider(decision_request(snapshot, 'data:image/png;base64,TEST'),
                                       url='http://127.0.0.1:1/v1', api_key=None)
            transport.assert_not_called()

    def test_oversized_snapshot_has_recapture_error(self):
        with self.assertRaisesRegex(ValueError, 'at most 200'):
            self.snapshot(candles(201))

    def test_forming_candle_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'completed candle'):
            self.snapshot(candles(2), completed=False)

    def test_revised_candle_requires_recapture(self):
        rows = candles(2)
        changed = [{**c, 'close': 11} for c in rows]
        with self.assertRaisesRegex(ValueError, 'reload and recapture'):
            self.store.create_snapshot('AAPL', '1m', rows[-1]['timestamp'], rows,
                context=dict(candles=changed, status=[]))

    def test_json_byte_limit_is_checked(self):
        body = {'input': [{'content': [{'type': 'input_json', 'data': {'large': 'x' * (256 * 1024)}}]}]}
        with self.assertRaisesRegex(ValueError, 'provider evidence limit'):
            validate_provider_input(body)


if __name__ == '__main__':
    unittest.main(verbosity=2)
