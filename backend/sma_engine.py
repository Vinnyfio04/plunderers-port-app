"""Shared trailing SMA/crossover math. No account writes or trade execution."""
from collections import deque
from decimal import Decimal, localcontext
import math


def _window(window):
    if isinstance(window, bool) or not isinstance(window, int) or not 1 <= window <= 10000:
        raise ValueError('SMA window must be an integer from 1 through 10000.')
    return window


def _inputs(candles, status):
    completion = {item['timestamp']: item for item in status}
    result = []
    previous = None
    for candle in candles:
        timestamp = candle['timestamp']
        if previous is not None and timestamp <= previous:
            raise ValueError('SMA candles must have unique, increasing UTC timestamps.')
        previous = timestamp
        close = candle['close']
        if isinstance(close, bool) or not isinstance(close, (int, float)) or not math.isfinite(close):
            raise ValueError('SMA close must be finite and numeric.')
        flags = completion.get(timestamp, {})
        # Older internal fixtures omit coverage; explicit partial coverage is never eligible.
        eligible = flags.get('interval_ended') is True and flags.get('coverage_complete', True) is True
        result.append((timestamp, str(close), eligible))
    return result


def sma_batch(window, candles, status):
    """Independent full-window summation, retained as the batch correctness baseline."""
    window = _window(window)
    completed = []
    points = []
    with localcontext() as context:
        context.prec = 50
        for timestamp, close, eligible in _inputs(candles, status):
            value = None
            if eligible:
                completed.append(Decimal(close))
                if len(completed) >= window:
                    value = float(sum(completed[-window:], Decimal(0)) / window)
            points.append(dict(timestamp=timestamp, value=value))
    return points


class IncrementalSMA:
    """Append/update a bounded chart context; revisions rebuild only its changed suffix."""
    def __init__(self, window):
        self.window = _window(window)
        self.inputs = []
        self.points = []
        self.queue = deque()
        self.total = Decimal(0)
        self.recomputed = 0

    def sync(self, candles, status):
        incoming = _inputs(candles, status)
        changed = 0
        while changed < min(len(incoming), len(self.inputs)) and incoming[changed] == self.inputs[changed]:
            changed += 1
        self.recomputed = len(incoming) - changed
        if incoming == self.inputs:
            return [dict(point) for point in self.points]
        with localcontext() as context:
            context.prec = 50
            if changed != len(self.inputs):
                # Restore the prior rolling window without rescanning all earlier prices.
                preceding = []
                for _, close, eligible in reversed(incoming[:changed]):
                    if eligible:
                        preceding.append(Decimal(close))
                        if len(preceding) == self.window:
                            break
                self.queue = deque(reversed(preceding))
                self.total = sum(self.queue, Decimal(0))
            self.points = self.points[:changed]
            for timestamp, close, eligible in incoming[changed:]:
                value = None
                if eligible:
                    number = Decimal(close)
                    self.queue.append(number)
                    self.total += number
                    if len(self.queue) > self.window:
                        self.total -= self.queue.popleft()
                    if len(self.queue) == self.window:
                        value = float(self.total / self.window)
                self.points.append(dict(timestamp=timestamp, value=value))
        self.inputs = incoming
        return [dict(point) for point in self.points]


def crossover_series(fast_values, slow_values):
    """A missing value breaks comparison; near-equality is a tie, never a signal."""
    fast = {point['timestamp']: point['value'] for point in fast_values}
    slow = {point['timestamp']: point['value'] for point in slow_values}
    previous = None
    output = []
    for timestamp in sorted(set(fast) | set(slow)):
        f, s = fast.get(timestamp), slow.get(timestamp)
        finite = all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) for value in (f, s))
        sign = 0 if finite and math.isclose(f, s, rel_tol=1e-12, abs_tol=1e-12) else (1 if finite and f > s else -1)
        signal = 'none'
        available = finite and previous is not None
        if available:
            if previous['sign'] <= 0 and sign > 0:
                signal = 'upward'
            elif previous['sign'] >= 0 and sign < 0:
                signal = 'downward'
        output.append(dict(timestamp=timestamp, available=available, signal=signal,
                           fastValue=f if finite else None, slowValue=s if finite else None,
                           previous={key: previous[key] for key in ('timestamp', 'fast', 'slow')} if available else None))
        previous = dict(timestamp=timestamp, fast=f, slow=s, sign=sign) if finite else None
    return output


def calculate_crossover(indicators, cutoff):
    """Legacy pair selection, shared arithmetic; selected cutoff must itself be ready."""
    sma = sorted((item for item in indicators if item['type'] == 'sma'),
                 key=lambda item: (item['settings']['window'], item['indicator_id']))
    if len(sma) < 2 or sma[0]['settings']['window'] == sma[-1]['settings']['window']:
        return dict(signal='none', available=False, reason='Two SMA instances with different windows are required.')
    fast, slow = sma[0], sma[-1]
    point = next((point for point in crossover_series(fast['values'], slow['values']) if point['timestamp'] == cutoff), None)
    if not point or not point['available']:
        return dict(signal='none', available=False, fast=fast['name'], slow=slow['name'],
                    reason='The selected cutoff does not have two comparable SMA values.')
    return dict(signal=point['signal'], available=True, fast=fast['name'], slow=slow['name'],
                previous=point['previous'], current=dict(timestamp=cutoff, fast=point['fastValue'], slow=point['slowValue']))
