"""Bounded causal SMA backtests over immutable inputs; never the live paper account."""
from datetime import datetime, timezone
from itertools import groupby
import hashlib
import json
import math

from backend.accounting import cents_to_dollars, dollars_to_cents, quote_entry
from backend.simulation_account import SimulationAccount
from backend.sma_engine import IncrementalSMA, crossover_series

ENGINE_VERSION = 'sma-crossover-v1'
MAX_BARS = 10000
MAX_EVENTS = 50000


def utc(value):
    if not isinstance(value, str):
        raise ValueError('Backtest times must be ISO strings with a timezone.')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Backtest times must include a timezone.')
    return parsed.astimezone(timezone.utc)


def text(value):
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def settings(payload):
    symbol = payload.get('symbol', 'AAPL')
    timeframe = payload.get('timeframe', '1m')
    mode = payload.get('data_mode', 'historical_bars')
    if not isinstance(symbol, str) or not symbol.strip() or len(symbol) > 32:
        raise ValueError('A stored ticker is required.')
    if timeframe not in ('1m', '5m', '15m', '1h', '1d') or mode not in ('historical_bars', 'recorded'):
        raise ValueError('Unsupported backtest interval or data mode.')
    if mode == 'recorded' and timeframe != '1m':
        raise ValueError('Strict recorded-availability backtests currently require 1m.')
    start, end = utc(payload.get('start')), utc(payload.get('end'))
    if start >= end:
        raise ValueError('Backtest start must precede end.')
    fast, slow, quantity = payload.get('fast_window'), payload.get('slow_window'), payload.get('quantity', 1)
    for value in (fast, slow, quantity):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError('SMA lengths and quantity must be integers.')
    if not 1 <= fast < slow <= 10000 or not 1 <= quantity <= 1000000:
        raise ValueError('Require 1 <= fast < slow <= 10000 and quantity 1–1000000.')
    cash = dollars_to_cents(payload.get('starting_cash', 10000))
    if cash > 100000000000000:
        raise ValueError('Starting cash exceeds the supported limit.')
    vintage = text(utc(payload['frozen_at'])) if payload.get('frozen_at') else None
    if vintage and utc(vintage) < end:
        raise ValueError('The frozen data vintage must be at or after the backtest end.')
    return dict(symbol=symbol.strip().upper(), timeframe=timeframe, data_mode=mode,
                start=text(start), end=text(end), fast_window=fast, slow_window=slow,
                quantity=quantity, starting_cash=cents_to_dollars(cash), frozen_at=vintage)


def _stable(value):
    if isinstance(value, dict):
        return {key: _stable(item) for key, item in value.items() if key != 'run_id'}
    return [_stable(item) for item in value] if isinstance(value, list) else value


def run_backtest(config, dataset):
    """Process only the visible prefix; a recorded receipt cannot fill its own signal."""
    config = settings(config)
    start, end = utc(config['start']), utc(config['end'])
    if any(dataset.get(key) != config[key] for key in ('symbol', 'timeframe', 'data_mode')):
        raise ValueError('Frozen dataset does not match the requested strategy context.')
    if utc(dataset['frozen_at']) < end:
        raise ValueError('Dataset vintage precedes the requested end.')
    config['frozen_at'] = dataset['frozen_at']
    if len(dataset.get('bars', [])) > MAX_EVENTS or len(dataset.get('prices', [])) > MAX_EVENTS:
        raise ValueError('Frozen dataset exceeds the event limit.')
    historical = config['data_mode'] == 'historical_bars'
    sim = SimulationAccount(symbol=config['symbol'], starting_cash=config['starting_cash'],
                            execution='bar_open' if historical else 'observation')
    events = []
    unique = set()
    trade_bars = set()
    for index, raw in enumerate(dataset.get('bars', [])):
        row = dict(raw)
        timestamp, close_time, available = utc(row['timestamp']), utc(row['end_time']), utc(row['available_at'])
        if close_time <= timestamp:
            raise ValueError('Bar end must follow its start.')
        if available > utc(dataset['frozen_at']):
            raise ValueError('A bar was not available at the declared frozen vintage.')
        for field in ('open', 'high', 'low', 'close'):
            value = row[field]
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
                raise ValueError('OHLC prices must be finite positive numbers.')
        if row['low'] > min(row['open'], row['close']) or row['high'] < max(row['open'], row['close']) or row['high'] < row['low']:
            raise ValueError('Invalid OHLC bounds.')
        volume = row.get('volume')
        if volume is not None and (isinstance(volume, bool) or not isinstance(volume, (int,float)) or not math.isfinite(volume) or volume < 0):
            raise ValueError('Volume must be nonnegative or unknown.')
        if not isinstance(row.get('complete'), bool) or not isinstance(row.get('coverage_complete'), bool):
            raise ValueError('Backtest completion/coverage flags must be explicit booleans.')
        if historical and row['timestamp'] in unique:
            raise ValueError('Historical-bar snapshots must contain one version per candle.')
        unique.add(row['timestamp'])
        if start <= timestamp < end:
            trade_bars.add(row['timestamp'])
        when = close_time if historical else max(available, close_time) if row['complete'] else available
        if when <= end:
            events.append((when, 'bar', index, row))
        if historical and start <= timestamp < end:
            # The open is assumed known at bar start; do not condition its execution
            # eligibility on this bar's later close/completion/coverage outcome.
            events.append((timestamp, 'price', index, dict(event_id=f'open:{row["timestamp"]}', price=row['open'])))
    if not trade_bars:
        raise ValueError('No stored bars are available in this date range and data mode.')
    if len(trade_bars) > MAX_BARS:
        raise ValueError('Backtest exceeds 10000 trading candles; select a shorter range.')
    if not historical:
        for index, row in enumerate(dataset.get('prices', [])):
            when = utc(row['available_at'])
            if when > utc(dataset['frozen_at']):
                raise ValueError('A price event was not available at the frozen vintage.')
            if start <= when < end:
                events.append((when, 'price', index, row))
    if len(events) > MAX_EVENTS:
        raise ValueError('Backtest exceeds 50000 scheduled events; select a shorter range.')
    known = {}
    decisions = []
    last_decided = None
    fast = IncrementalSMA(config['fast_window'])
    slow = IncrementalSMA(config['slow_window'])
    historical_points = {}
    if historical:
        # Trailing means are prefix-invariant; precomputing the fixed-vintage
        # series avoids quadratic rescans, without exposing future opens to decisions.
        rows = sorted((row for row in dataset['bars'] if utc(row['end_time']) <= end), key=lambda row: row['timestamp'])
        flags = [dict(timestamp=row['timestamp'], interval_ended=row['complete'], coverage_complete=row['coverage_complete']) for row in rows]
        historical_points = {point['timestamp']: point for point in crossover_series(fast.sync(rows,flags),slow.sync(rows,flags))}
    events.sort(key=lambda item: (item[0], item[2]))
    for when, group in groupby(events, key=lambda item: item[0]):
        batch = list(group)
        prices = [event for event in batch if event[1] == 'price']
        if not historical:
            # Quotes that contributed to a same-time bar update are already known;
            # they cannot fill an order produced by that update.
            for _, _, _, price in prices:
                sim.observe(event_id=price['event_id'], price=price['price'], available_at=when)
        updated = set()
        for _, kind, _, row in batch:
            if kind != 'bar':
                continue
            known[row['timestamp']] = row
            updated.add(row['timestamp'])
        candidates = [key for key in updated if known[key]['complete'] and utc(known[key]['end_time']) <= when]
        if candidates:
            candle_time = max(candidates)
            # Revisions inform subsequent indicators, never rewrite a past trade.
            if (last_decided is None or candle_time > last_decided) and start <= utc(candle_time) < end:
                if historical:
                    point = historical_points[candle_time]
                else:
                    rows = [known[key] for key in sorted(known) if key <= candle_time]
                    flags = [dict(timestamp=row['timestamp'], interval_ended=row['complete'] and utc(row['end_time']) <= when,
                                  coverage_complete=row['coverage_complete']) for row in rows]
                    point = crossover_series(fast.sync(rows, flags), slow.sync(rows, flags))[-1]
                candle = known[candle_time]
                sim.mark(event_id=f'close:{candle_time}', price=candle['close'] if candle['coverage_complete'] else None, available_at=when)
                current = sim.current()
                action, reason, order = None, 'Indicator warm-up or incomplete evidence.', None
                if point['available']:
                    action = 'hold' if current['shares'] else 'wait'
                    reason = 'No entry/exit crossover for the current position.'
                    if current['pending_orders']:
                        action, reason = 'pending', 'Wait for the previously submitted order; do not duplicate it.'
                    elif point['signal'] == 'upward' and current['shares'] == 0:
                        cost = quote_entry(candle['close'], config['quantity'])['estimated_cost_cents']
                        if cost <= current['cash_cents']:
                            action, reason = 'buy', 'Upward crossover while flat; indicative cash gate passed.'
                        else:
                            action, reason = 'wait', 'Cash cannot cover the configured quantity at this close.'
                    elif point['signal'] == 'downward' and current['shares'] > 0:
                        action, reason = 'close', 'Downward crossover; close the long position.'
                    if action in ('buy', 'close'):
                        order = sim.submit(request_id=f'decision:{candle_time}', action=action,
                                           quantity=config['quantity'], submitted_at=when)
                decisions.append(dict(bar_time=candle_time, decision_time=text(when), signal=point['signal'],
                                      available=point['available'], fast=point['fastValue'], slow=point['slowValue'],
                                      action=action, reason=reason, order_id=order['order_id'] if order else None))
                last_decided = candle_time
        if historical:
            # Previous bar's close/decision precedes the next bar's open at a boundary.
            for _, _, _, price in prices:
                sim.bar_open(event_id=price['event_id'], open_price=price['price'], bar_start=when)
    final = sim.snapshot()
    initial, equity = final['initial_cash'], final['equity']
    summary = dict(initial_cash=initial, equity=equity, cash=final['cash'], shares=final['shares'],
                   realized=final['realized'], unrealized=final['unrealized'], total_pnl=final['total_pnl'],
                   return_percent=(equity / initial - 1) * 100 if equity is not None else None,
                   decisions=len(decisions), fills=sum(row['status'] == 'filled' for row in final['orders']),
                   rejected=sum(row['status'] == 'rejected' for row in final['orders']),
                   pending=sum(row['status'] == 'pending' for row in final['orders']), trading_bars=len(trade_bars))
    summary['warmup_bars'] = len({row['timestamp'] for row in dataset['bars'] if utc(row['timestamp']) < start})
    limitations = [
        'Simulated results under long-only, whole-share, zero fee/added slippage assumptions; not evidence of future profitability.',
        'No forced liquidation. Remaining positions are marked at the last usable price; final signals can leave an unfilled pending order.',
        'Available data may be incomplete, revised, unadjusted or omit dividends/splits; no missing bars are invented.',
        ('Fixed-vintage bars assume close availability at bar end; historical original knowledge/revision timing cannot be reconstructed.' if historical else
         'Recorded 1m mode respects saved availability; same-time receipts precede decisions and cannot fill their own signal. Backfills do not trigger retroactive trades.'),
    ]
    result = dict(run_id=sim.run_id, engine_version=ENGINE_VERSION, settings=config, dataset_hash=digest(dataset),
                  summary=summary, decisions=decisions, orders=final['orders'], equity=final['pnl_history'],
                  final_state=final, limitations=limitations)
    result['result_hash'] = digest(_stable(result))
    return result
