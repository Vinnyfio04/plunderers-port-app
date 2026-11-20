"""Bounded history from indexed effective minute candles."""
from datetime import datetime, timezone
import json
from contextlib import nullcontext
from types import SimpleNamespace
from backend.market_store import MarketRecorder
from backend.candle_store import read_minutes, candle_dict, stamp, session_bounds
from backend.timeframe_history import MinuteRecord, aggregate_timeframe
from backend.yahoo_history import market_status
from backend.daily_history import page as daily_page
from backend.interval_history import page as interval_page, POLICIES, window_start


def recorded_history(database, symbol, timeframe, as_of=None, limit=2000, before=None, start=None, apply_policy=False, connection=None):
    now = as_of or datetime.now(timezone.utc)
    if apply_policy and POLICIES[timeframe]['lookback_days']:
        floor = window_start(timeframe,now)
        if not start or datetime.fromisoformat(start.replace('Z','+00:00'))<datetime.fromisoformat(floor):
            start = floor
    multiplier = {'1m':1,'5m':5,'15m':15,'1h':60,'1d':390}[timeframe]
    minute_limit = min(20000 if timeframe=='1m' else 10000, limit*multiplier+multiplier)
    with (nullcontext(SimpleNamespace(connection=connection)) if connection is not None else MarketRecorder(database)) as recorder:
        c = recorder.connection
        if not c.in_transaction:
            c.execute('BEGIN')  # Rows and revision cursors describe one committed snapshot.
        rows = read_minutes(c,symbol,minute_limit,before,start,as_of)
        watermark = c.execute('SELECT COALESCE(MAX(revision_id),0) FROM candle_revisions').fetchone()[0]
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        fetch = c.execute('SELECT status,fetched_at,message FROM yahoo_history_fetches WHERE ticker=? ORDER BY fetch_id DESC LIMIT 1',(symbol,)).fetchone() if 'yahoo_history_fetches' in tables else None
        latest = c.execute('''SELECT o.source_time_utc, o.raw_payload_json, r.backend_receipt_time_utc FROM receipts r
            JOIN observations o USING(observation_id) WHERE r.instrument_id=(SELECT instrument_id FROM instruments WHERE symbol=?)
            AND r.receipt_ms<=? ORDER BY r.receipt_id DESC LIMIT 1''',(symbol,round(now.timestamp()*1000))).fetchone()
        daily = daily_page(c,symbol,limit,before,start,as_of) if timeframe=='1d' else None
        intraday = interval_page(c,symbol,timeframe,limit,before,start,as_of) if timeframe in ('5m','15m','1h') else None
        first_minute = c.execute('''SELECT minute_start FROM candles_1m
            WHERE instrument_id=(SELECT instrument_id FROM instruments WHERE symbol=?) AND minute_start>=?
            ORDER BY minute_start LIMIT 1''',(symbol,int(datetime.fromisoformat(start.replace('Z','+00:00')).timestamp()) if start else 0)).fetchone() if timeframe=='1m' else None
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
    has_more = len(rows)>=minute_limit
    provider = daily or intraday
    if provider:
        # Retain fully covered minute aggregates; replace partial coverage with provider bars.
        merged = {x['timestamp']:(x,s) for x,s in zip(result['candles'],result['status'])}
        for candle,completion in zip(provider['candles'],provider['status']):
            existing = merged.get(candle['timestamp'])
            if existing and existing[1]['coverage_complete']:
                existing[1].update(price_source='Aggregated one-minute candles',source_resolution='1m',coverage_basis='recorded minute coverage')
            else:
                merged[candle['timestamp']] = (candle,completion)
        ordered = [merged[key] for key in sorted(merged)]
        result['candles'] = [x[0] for x in ordered]
        result['status'] = [x[1] for x in ordered]
        has_more = has_more or provider['has_more'] or len(ordered)>limit
    result['candles'], result['status'] = result['candles'][-limit:],result['status'][-limit:]
    payload = json.loads(latest['raw_payload_json']) if latest else {}
    latest_time = max(filter(None,[latest['source_time_utc'] if latest else None,candles[-1]['timestamp'] if candles else None]), default=None)
    return {**result,'source':('Yahoo Finance daily history + live minute aggregation' if daily and daily['daily_earliest'] else f'Yahoo Finance {timeframe} history + live minute aggregation' if intraday and intraday['history_earliest'] else payload.get('test_data_label','Yahoo Finance minute history + WebSocket')),
        'data_kind':'test' if payload.get('test_data') else 'recorded','latest_source_time':latest_time,
        'latest_receipt_time':latest['backend_receipt_time_utc'] if latest else None,
        'market':market_status(now),'history_fetch':daily['daily_fetch'] if daily and daily['daily_fetch'] else intraday['history_fetch'] if intraday and intraday['history_fetch'] else dict(fetch) if fetch else None,'watermark':watermark,
        'history_policy':dict(POLICIES[timeframe]),
        'history_earliest':daily['daily_earliest'] if daily else intraday['history_earliest'] if intraday and intraday['history_earliest'] else stamp(first_minute[0]) if first_minute else result['candles'][0]['timestamp'] if result['candles'] else None,
        'interval_watermark':intraday['interval_watermark'] if intraday else 0,
        'daily_earliest':daily['daily_earliest'] if daily else None,
        'daily_latest':daily['daily_latest'] if daily else None,
        'daily_watermark':daily['daily_watermark'] if daily else 0,
        'next_before':result['candles'][0]['timestamp'] if has_more and result['candles'] else None,
        'volume_note':'Completed Yahoo bars replace partial local coverage at the matching resolution. Provisional or missing volume is Unknown; volumes are never added twice.',
        'message':None if result['candles'] else 'No recorded regular-session candles. Waiting for live observations.'}
