"""The shared live/history view of persisted source observations."""
from datetime import datetime, timezone
import json

from backend.candle_aggregation import aggregate_ticker
from backend.market_store import MarketRecorder
from backend.timeframe_history import MinuteRecord, aggregate_timeframe
from backend.yahoo_history import initialize, available_bars, market_status


def recorded_history(database, symbol, timeframe, as_of=None):
    now = as_of or datetime.now(timezone.utc)
    initialize(database)
    with MarketRecorder(database) as recorder:
        minute = aggregate_ticker(recorder, symbol, now)
        bars = available_bars(recorder.connection, symbol, now)
        observations = recorder.list_effective_observations(symbol, now)
        fetch = recorder.connection.execute('''SELECT status, fetched_at, message FROM yahoo_history_fetches
            WHERE ticker=? AND julianday(fetched_at)<=julianday(?) ORDER BY fetch_id DESC LIMIT 1''',
            (symbol, now.isoformat())).fetchone()
        latest = recorder.connection.execute(
            """SELECT o.source_time_utc, r.backend_receipt_time_utc, o.raw_payload_json
               FROM receipts r JOIN observations o USING(observation_id)
               WHERE o.ticker=? AND julianday(r.backend_receipt_time_utc) <= julianday(?)
               ORDER BY r.receipt_id DESC LIMIT 1""",
            (symbol, now.isoformat().replace('+00:00', 'Z')),
        ).fetchone()
    merged = {c['timestamp']: c for c in minute.candles}
    provenance = {c['timestamp']: 'Yahoo WebSocket observations' for c in minute.candles}
    for timestamp, bar in bars.items():
        candle = json.loads(bar['candle_json'])
        if not bar['completed']:
            start = datetime.fromisoformat(timestamp.replace('Z', '+00:00')).timestamp()
            cutoff = datetime.fromisoformat(bar['snapshot_at'].replace('Z', '+00:00')).timestamp()
            newer = [o for o in observations if max(start, cutoff) * 1000 < o['source_time_epoch_ms'] < (start + 60)*1000]
            if newer:
                candle = {**candle, 'high': max(candle['high'], *(o['price'] for o in newer)),
                          'low': min(candle['low'], *(o['price'] for o in newer)), 'close': newer[-1]['price'],
                          'volume': None}
        # A completed Yahoo bar replaces the entire observed minute, never adds its volume.
        merged[timestamp] = candle
        provenance[timestamp] = 'Yahoo minute history' if bar['completed'] else 'Yahoo provisional minute + observations'
    result = aggregate_timeframe(
        [MinuteRecord(candle=c, available_at=now) for c in merged.values()],
        timeframe=timeframe, as_of=now,
    )
    payload = json.loads(latest['raw_payload_json']) if latest else {}
    source = payload.get('test_data_label', 'Recorded Yahoo Finance observations')
    if bars:
        source = 'Yahoo Finance minute history + WebSocket'
    for candle, status in zip(result['candles'], result['status']):
        status['price_source'] = provenance.get(candle['timestamp'], 'Backend minute aggregation') if timeframe == '1m' else 'Backend aggregation of Yahoo minutes'
        status['volume_source'] = 'Yahoo reported minute volume or observed cumulative difference' if candle['volume'] is not None else 'Unknown; awaiting reconciliation'
    latest_bar_time = max(bars) if bars else None
    latest_source_time = max(filter(None, [latest['source_time_utc'] if latest else None, latest_bar_time]), default=None)
    return {**result, 'source': source, 'data_kind': 'test' if payload.get('test_data') else 'recorded',
            'latest_source_time': latest_source_time,
            'latest_receipt_time': latest['backend_receipt_time_utc'] if latest else None,
            'market': market_status(now), 'history_fetch': dict(fetch) if fetch else None,
            'volume_note': 'Completed Yahoo bars replace observed minutes, including volume. Provisional overlays have unknown volume until reconciled; volume is never added twice.',
            'message': None if result['candles'] else 'No recorded regular-session candles. Waiting for live observations.'}
