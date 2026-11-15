"""Bounded history from indexed effective minute candles."""
from datetime import datetime, timezone
import json
from backend.market_store import MarketRecorder
from backend.candle_store import read_minutes, candle_dict, stamp, session_bounds
from backend.timeframe_history import MinuteRecord, aggregate_timeframe
from backend.yahoo_history import market_status


def recorded_history(database, symbol, timeframe, as_of=None, limit=2000, before=None, start=None):
    now = as_of or datetime.now(timezone.utc)
    multiplier = {'1m':1,'5m':5,'15m':15,'1h':60,'1d':390}[timeframe]
    minute_limit = min(20000 if timeframe=='1m' else 10000, limit*multiplier+multiplier)
    with MarketRecorder(database) as recorder:
        c = recorder.connection
        rows = read_minutes(c,symbol,minute_limit,before,start,as_of)
        watermark = c.execute('SELECT COALESCE(MAX(revision_id),0) FROM candle_revisions').fetchone()[0]
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        fetch = c.execute('SELECT status,fetched_at,message FROM yahoo_history_fetches WHERE ticker=? ORDER BY fetch_id DESC LIMIT 1',(symbol,)).fetchone() if 'yahoo_history_fetches' in tables else None
        latest = c.execute('''SELECT o.source_time_utc, o.raw_payload_json, r.backend_receipt_time_utc FROM receipts r
            JOIN observations o USING(observation_id) WHERE r.instrument_id=(SELECT instrument_id FROM instruments WHERE symbol=?)
            AND r.receipt_ms<=? ORDER BY r.receipt_id DESC LIMIT 1''',(symbol,round(now.timestamp()*1000))).fetchone()
    candles = [candle_dict(r) for r in rows]
    if timeframe == '1m':
        status = []
        for row, candle in zip(rows,candles):
            bounds = session_bounds(row['session'])
            status.append(dict(timestamp=candle['timestamp'],session=row['session'],session_open=stamp(bounds[0]),
                session_close=stamp(bounds[1]),available_minutes=1,expected_minutes=1,coverage_complete=True,
                interval_ended=now.timestamp()>=row['minute_start']+60,volume_known=row['volume'] is not None,
                price_source=row['source']))
        result = dict(timeframe=timeframe,calendar='XNYS',as_of=now.isoformat(),candles=candles,status=status)
    else:
        result = aggregate_timeframe([MinuteRecord(candle=x,available_at=now) for x in candles],timeframe,now)
        if rows and len(rows)==minute_limit and result['candles']:
            result['candles'] = result['candles'][1:]
            result['status'] = result['status'][1:]
    result['candles'], result['status'] = result['candles'][-limit:],result['status'][-limit:]
    payload = json.loads(latest['raw_payload_json']) if latest else {}
    latest_time = max(filter(None,[latest['source_time_utc'] if latest else None,candles[-1]['timestamp'] if candles else None]), default=None)
    return {**result,'source':payload.get('test_data_label','Yahoo Finance minute history + WebSocket'),
        'data_kind':'test' if payload.get('test_data') else 'recorded','latest_source_time':latest_time,
        'latest_receipt_time':latest['backend_receipt_time_utc'] if latest else None,
        'market':market_status(now),'history_fetch':dict(fetch) if fetch else None,'watermark':watermark,
        'next_before':result['candles'][0]['timestamp'] if len(rows)>=minute_limit and result['candles'] else None,
        'volume_note':'Completed Yahoo bars replace observed minutes. Provisional or missing volume is Unknown; volumes are never added twice.',
        'message':None if candles else 'No recorded regular-session candles. Waiting for live observations.'}
