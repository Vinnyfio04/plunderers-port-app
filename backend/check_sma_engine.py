"""Independent pandas reference, batch/incremental, availability and revision checks."""
from datetime import datetime, timedelta, timezone
import math
import random
import unittest

import pandas as pd

from backend.indicators import calculate_indicator
from backend.sma_engine import IncrementalSMA, calculate_crossover, crossover_series, sma_batch


def fixture(prices):
    start = datetime(2026, 11, 9, 14, 30, tzinfo=timezone.utc)
    candles = [dict(timestamp=(start + timedelta(minutes=i)).isoformat().replace('+00:00', 'Z'),
                    close=price) for i, price in enumerate(prices)]
    status = [dict(timestamp=row['timestamp'], interval_ended=True, coverage_complete=True) for row in candles]
    return candles, status


def reference(window, candles, status):
    eligible = {item['timestamp'] for item in status if item['interval_ended'] and item.get('coverage_complete', True)}
    selected = [row for row in candles if row['timestamp'] in eligible]
    means = pd.Series([row['close'] for row in selected], index=[row['timestamp'] for row in selected], dtype=float).rolling(window, min_periods=window, center=False).mean()
    return [None if row['timestamp'] not in means or pd.isna(means[row['timestamp']]) else means[row['timestamp']] for row in candles]


class SmaChecks(unittest.TestCase):
    def matches_reference(self, window, candles, status, points):
        for point, expected in zip(points, reference(window, candles, status), strict=True):
            if expected is None:
                self.assertIsNone(point['value'])
            else:
                self.assertTrue(math.isclose(point['value'], expected, abs_tol=1e-10, rel_tol=1e-12), (point, expected))

    def test_batch_incremental_and_pandas_every_prefix(self):
        rng = random.Random(402)
        candles, status = fixture([round(rng.uniform(20, 400), 7) for _ in range(130)])
        status[7]['interval_ended'] = False
        status[20]['coverage_complete'] = False
        for window in (1, 2, 3, 20, 10000):
            engine = IncrementalSMA(window)
            for length in range(1, len(candles) + 1):
                current = engine.sync(candles[:length], status[:length])
                self.assertEqual(engine.recomputed, 1, 'an append calculates one new output')
                self.assertEqual(current, sma_batch(window, candles[:length], status[:length]))
                self.matches_reference(window, candles[:length], status[:length], current)
            self.assertEqual(current, calculate_indicator('sma', {'window': window}, candles, status))

    def test_updates_completion_and_idempotency(self):
        candles, status = fixture([.1, .2, .3, .4])
        status[-1]['interval_ended'] = False
        engine = IncrementalSMA(2)
        for value in (10, 100, 999):
            candles[-1]['close'] = value
            actual = engine.sync(candles, status)
            self.assertIsNone(actual[-1]['value'])
            self.matches_reference(2, candles, status, actual)
        status[-1]['interval_ended'] = True
        actual = engine.sync(candles, status)
        self.assertEqual(engine.recomputed, 1)
        self.assertEqual(actual, sma_batch(2, candles, status))
        self.assertEqual(engine.sync(candles, status), actual)
        self.assertEqual(engine.recomputed, 0, 'same completed candle cannot enter the window twice')

    def test_revision_reorder_and_context_change(self):
        candles, status = fixture([10, 12, 9, 13, 9, 14, 11])
        engine = IncrementalSMA(3)
        original = engine.sync(candles, status)
        candles[2]['close'] = 90
        revised = engine.sync(candles, status)
        self.assertEqual(revised[:2], original[:2])
        self.assertEqual(engine.recomputed, 5)
        self.assertEqual(revised, sma_batch(3, candles, status))
        self.matches_reference(3, candles, status, revised)
        status[2]['coverage_complete'] = False
        self.assertEqual(engine.sync(candles, status), sma_batch(3, candles, status))
        self.assertEqual(engine.sync(candles[2:], status[2:]), sma_batch(3, candles[2:], status[2:]))
        for bad in (list(reversed(candles)), [candles[0], candles[0]]):
            with self.assertRaises(ValueError):
                engine.sync(bad, status)

    def test_known_values_ties_and_pandas_crossovers(self):
        candles, status = fixture([10, 10, 10, 12, 9, 13, 13, 13, 8])
        fast = sma_batch(1, candles, status)
        slow = sma_batch(2, candles, status)
        points = crossover_series(fast, slow)
        f = reference(1, candles, status)
        s = reference(2, candles, status)
        prior = None
        for point, first, second in zip(points, f, s, strict=True):
            if first is None or second is None:
                self.assertFalse(point['available'])
                prior = None
                continue
            sign = 0 if math.isclose(first, second, rel_tol=1e-12, abs_tol=1e-12) else (1 if first > second else -1)
            expected = 'upward' if prior is not None and prior <= 0 < sign else 'downward' if prior is not None and prior >= 0 > sign else 'none'
            self.assertEqual(point['signal'], expected)
            prior = sign
        self.assertEqual(points[2]['signal'], 'none', 'equality is not a crossover')
        self.assertEqual(points[3]['signal'], 'upward')
        self.assertEqual(points[4]['signal'], 'downward')
        self.assertEqual(slow[3]['value'], 11)

    def test_unavailable_cutoff_never_reuses_old_signal(self):
        candles, status = fixture([10, 12, 9, 13])
        status[-1]['interval_ended'] = False
        indicators = [dict(indicator_id=n, type='sma', name=str(n), settings={'window': n}, values=sma_batch(n, candles, status)) for n in (1, 2)]
        self.assertEqual(calculate_crossover(indicators, candles[2]['timestamp'])['signal'], 'downward')
        self.assertFalse(calculate_crossover(indicators, candles[-1]['timestamp'])['available'])
        status[2]['coverage_complete'] = False
        status[-1]['interval_ended'] = True
        points = crossover_series(sma_batch(1, candles, status), sma_batch(2, candles, status))
        self.assertFalse(points[-1]['available'], 'a missing/partial candle breaks comparison')

    def test_no_future_leak_and_near_equality(self):
        candles, status = fixture([10, 12, 9, 13, 2000])
        before = sma_batch(2, candles[:4], status[:4])
        self.assertEqual(sma_batch(2, candles, status)[:4], before)
        fast = [{'timestamp': 'a', 'value': 100}, {'timestamp': 'b', 'value': 100 + 1e-13}]
        slow = [{'timestamp': 'a', 'value': 100}, {'timestamp': 'b', 'value': 100}]
        self.assertEqual(crossover_series(fast, slow)[-1]['signal'], 'none')

    def test_maximum_window_and_output_isolation(self):
        candles, status = fixture([.1] * 10001)
        engine = IncrementalSMA(10000)
        points = engine.sync(candles, status)
        self.assertIsNone(points[9998]['value'])
        self.assertEqual(points[9999]['value'], .1)
        self.assertEqual(points, sma_batch(10000, candles, status))
        self.matches_reference(10000, candles, status, points)
        points[-1]['value'] = 999
        self.assertEqual(engine.sync(candles, status)[-1]['value'], .1)
        self.assertEqual(engine.recomputed, 0)

    def test_missing_flags_and_invalid_inputs(self):
        candles, status = fixture([10, 12, 9, 13])
        missing = [item for item in status if item['timestamp'] != candles[2]['timestamp']]
        points = crossover_series(sma_batch(1, candles, missing), sma_batch(2, candles, missing))
        self.assertFalse(points[-1]['available'])
        for window in (0, 10001, 1.5, True, '2'):
            with self.assertRaises(ValueError):
                IncrementalSMA(window)
        for value in (float('nan'), float('inf'), True, '10'):
            with self.assertRaises(ValueError):
                IncrementalSMA(2).sync([{**candles[0], 'close': value}], status)


if __name__ == '__main__':
    print(f'Trusted reference: pandas {pd.__version__}; rolling(N,min_periods=N,center=False).mean(); SMA tolerance abs=1e-10 rel=1e-12')
    unittest.main(verbosity=2)
