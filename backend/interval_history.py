"""Practical intraday backfill windows with indexed, revision-aware Yahoo bars."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math

import exchange_calendars as xc
import pandas as pd
import yfinance as yf


POLICIES = {
    '1m': dict(lookback_days=7,label='1-minute: 7 calendar days',bar_budget=5000),
    '5m': dict(lookback_days=60,label='5-minute: 60 calendar days',bar_budget=5000),
    '15m': dict(lookback_days=60,label='15-minute: 60 calendar days',bar_budget=5000),
    '1h': dict(lookback_days=730,label='Hourly: about 2 years',bar_budget=5000),
    '1d': dict(lookback_days=None,label='Daily: maximum available history',bar_budget=None),
}
INTERVAL_MINUTES = {'5m':5,'15m':15,'1h':60}


class IntervalDataError(ValueError):
    """A safe, actionable explanation for unavailable provider candle data."""

SCHEMA = '''
CREATE TABLE IF NOT EXISTS interval_candles (
    instrument_id INTEGER NOT NULL, interval TEXT NOT NULL, timestamp INTEGER NOT NULL,
    session TEXT NOT NULL, interval_end INTEGER NOT NULL, open REAL NOT NULL, high REAL NOT NULL,
    low REAL NOT NULL, close REAL NOT NULL, volume INTEGER, expected_minutes INTEGER NOT NULL,
    known_at_ms INTEGER NOT NULL, revision_id INTEGER NOT NULL,
    PRIMARY KEY(instrument_id,interval,timestamp)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS interval_revisions (
    revision_id INTEGER PRIMARY KEY, instrument_id INTEGER NOT NULL, interval TEXT NOT NULL,
    timestamp INTEGER NOT NULL, session TEXT NOT NULL, interval_end INTEGER NOT NULL,
    open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL, volume INTEGER,
    expected_minutes INTEGER NOT NULL, known_at_ms INTEGER NOT NULL, payload_hash TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS interval_revision_time ON interval_revisions(instrument_id,interval,timestamp,known_at_ms,revision_id);
CREATE INDEX IF NOT EXISTS interval_revision_changes ON interval_revisions(instrument_id,interval,revision_id);
CREATE TABLE IF NOT EXISTS interval_history_fetches (
    fetch_id INTEGER PRIMARY KEY,ticker TEXT NOT NULL,interval TEXT NOT NULL,fetched_at TEXT NOT NULL,
    known_at_ms INTEGER NOT NULL,status TEXT NOT NULL,bar_count INTEGER NOT NULL,message TEXT);
CREATE INDEX IF NOT EXISTS interval_fetch_symbol ON interval_history_fetches(ticker,interval,fetch_id);
'''


def window_start(interval, now=None):
    now = now or datetime.now(timezone.utc)
    days = POLICIES[interval]['lookback_days']
    return (now-timedelta(days=days)+timedelta(minutes=1)).isoformat() if days else None


def refresh_needed(database, symbol, interval, now=None):
    from backend.market_store import MarketRecorder
    now = now or datetime.now(timezone.utc)
    with MarketRecorder(database) as store:
        c = store.connection
        last = c.execute('''SELECT * FROM interval_history_fetches WHERE ticker=? AND interval=?
            ORDER BY fetch_id DESC LIMIT 1''',(symbol,interval)).fetchone()
        if not last:
            return True
        age = now.timestamp()-last['known_at_ms']/1000
        if age<60:
            return False
        cal = xc.get_calendar('XNYS')
        session = cal.date_to_session(pd.Timestamp(now.date()),direction='previous')
        opening,closing = cal.session_open(session),cal.session_close(session)
        if pd.Timestamp(now)<opening:
            session = cal.previous_session(session)
            opening,closing = cal.session_open(session),cal.session_close(session)
        if pd.Timestamp(now)<closing:  # Incremental reconciliation while the session is open.
            return True
        latest = c.execute('''SELECT interval_end FROM interval_candles
            WHERE instrument_id=(SELECT instrument_id FROM instruments WHERE symbol=?) AND interval=?
            ORDER BY timestamp DESC LIMIT 1''',(symbol,interval)).fetchone()
        return not (last['status']=='ok' and age<86400 and latest and latest[0]>=closing.timestamp())


def download(database, symbol, interval):
    from backend.market_store import MarketRecorder
    from backend.candle_store import session_bounds,stamp
    started = datetime.now(timezone.utc)
    beginning = datetime.fromisoformat(window_start(interval,started))
    # A successful cache needs only an overlapping tail, not the entire window every minute.
    with MarketRecorder(database) as store:
        c = store.connection
        successful = c.execute('''SELECT known_at_ms FROM interval_history_fetches
            WHERE ticker=? AND interval=? AND status='ok' ORDER BY fetch_id DESC LIMIT 1''',(symbol,interval)).fetchone()
        latest = c.execute('''SELECT timestamp FROM interval_candles
            WHERE instrument_id=(SELECT instrument_id FROM instruments WHERE symbol=?) AND interval=?
            ORDER BY timestamp DESC LIMIT 1''',(symbol,interval)).fetchone()
    if successful and latest and started.timestamp()-successful[0]/1000<86400:
        beginning = max(beginning,datetime.fromtimestamp(latest[0],timezone.utc)-timedelta(minutes=2*INTERVAL_MINUTES[interval]))
    try:
        ticker = yf.Ticker(symbol)
        frame = ticker.history(start=beginning,interval=interval,prepost=False,
            auto_adjust=False,actions=False,timeout=10)
        if frame.empty and interval=='1h':
            # Yahoo occasionally returns an empty 1h range near its retention boundary.
            # One equivalent 60m request also bypasses that cached empty range; never loop.
            fallback_start = max(beginning,started-timedelta(days=729))
            frame = ticker.history(start=fallback_start,interval='60m',prepost=False,
                auto_adjust=False,actions=False,timeout=10)
        frame = frame.sort_index()
        if frame.empty:
            raise IntervalDataError('Yahoo returned no price bars. Try Latest again shortly')
        candles=[]
        step=INTERVAL_MINUTES[interval]*60
        for date,row in frame.iterrows():
            timestamp=int(date.timestamp())
            bounds=session_bounds(stamp(timestamp)[:10])
            if not bounds or not bounds[0]<=timestamp<bounds[1] or (timestamp-bounds[0])%step:
                continue
            end=min(timestamp+step,bounds[1])
            if end>started.timestamp() or row[['Open','High','Low','Close']].isna().any():
                continue
            prices=tuple(float(row[k]) for k in ('Open','High','Low','Close'))
            volume=None if pd.isna(row.Volume) else float(row.Volume)
            if (not all(math.isfinite(x) and x>0 for x in prices) or prices[1]<max(prices) or prices[2]>min(prices)
                    or (volume is not None and (not math.isfinite(volume) or volume<0 or not volume.is_integer()))):
                raise IntervalDataError('Yahoo returned invalid candle prices or volume')
            candles.append((timestamp,stamp(bounds[0])[:10],end,*prices,None if volume is None else int(volume),(end-timestamp)//60))
        if not candles:
            raise IntervalDataError('Yahoo returned no completed regular-session bars')
        return dict(status='ok',message=None,candles=candles,fetched=datetime.now(timezone.utc))
    except Exception as error:
        reason = str(error) if isinstance(error,IntervalDataError) else 'The upstream request failed; try Latest again shortly'
        return dict(status='unavailable',message=f'Yahoo {interval} history unavailable: {reason}. Keeping saved candles.',
                    candles=[],fetched=datetime.now(timezone.utc))


def persist(database, symbol, interval, result):
    from backend.market_store import MarketRecorder
    from backend.candle_store import instrument
    known=round(result['fetched'].timestamp()*1000)
    with MarketRecorder(database) as store:
        c=store.connection
        with c:
            iid=instrument(c,symbol)
            for row in result['candles']:
                digest=hashlib.sha256(json.dumps(row,allow_nan=False).encode()).hexdigest()
                prior=c.execute('''SELECT payload_hash FROM interval_revisions WHERE instrument_id=? AND interval=?
                    AND timestamp=? ORDER BY revision_id DESC LIMIT 1''',(iid,interval,row[0])).fetchone()
                if prior and prior[0]==digest:
                    continue
                revision=c.execute('''INSERT INTO interval_revisions(instrument_id,interval,timestamp,session,interval_end,
                    open,high,low,close,volume,expected_minutes,known_at_ms,payload_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (iid,interval,*row,known,digest)).lastrowid
                c.execute('''INSERT INTO interval_candles VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(instrument_id,interval,timestamp) DO UPDATE SET interval_end=excluded.interval_end,
                    open=excluded.open,high=excluded.high,low=excluded.low,close=excluded.close,volume=excluded.volume,
                    expected_minutes=excluded.expected_minutes,known_at_ms=excluded.known_at_ms,revision_id=excluded.revision_id''',
                    (iid,interval,*row,known,revision))
            c.execute('''INSERT INTO interval_history_fetches(ticker,interval,fetched_at,known_at_ms,status,bar_count,message)
                VALUES (?,?,?,?,?,?,?)''',(symbol,interval,result['fetched'].isoformat().replace('+00:00','Z'),known,result['status'],len(result['candles']),result['message']))


def page(c, symbol, interval, limit, before=None, start=None, as_of=None):
    from backend.candle_store import epoch,stamp,session_bounds
    cutoff=round((as_of or datetime.now(timezone.utc)).timestamp()*1000)
    iid=c.execute('SELECT instrument_id FROM instruments WHERE symbol=?',(symbol,)).fetchone()
    if not iid:
        return None
    iid=iid[0]
    begin,end=epoch(start)//1000 if start else -(2**62),epoch(before)//1000 if before else 2**62
    table='interval_revisions' if as_of else 'interval_candles'
    extra='''AND revision_id=(SELECT MAX(x.revision_id) FROM interval_revisions x WHERE x.instrument_id=b.instrument_id
        AND x.interval=b.interval AND x.timestamp=b.timestamp AND x.known_at_ms<=?)''' if as_of else ''
    args=(iid,interval,begin,end,cutoff,cutoff//1000)+((cutoff,) if as_of else ())+(limit+1,)
    rows=c.execute(f'''SELECT * FROM {table} b WHERE instrument_id=? AND interval=? AND timestamp>=? AND timestamp<?
        AND known_at_ms<=? AND interval_end<=? {extra} ORDER BY timestamp DESC LIMIT ?''',args).fetchall()
    more=len(rows)>limit
    rows=rows[:limit][::-1]
    first=c.execute(f'''SELECT timestamp FROM {table} WHERE instrument_id=? AND interval=? AND timestamp>=?
        AND known_at_ms<=? ORDER BY timestamp LIMIT 1''',(iid,interval,begin,cutoff)).fetchone()
    fetch=c.execute('''SELECT status,fetched_at,message FROM interval_history_fetches WHERE ticker=? AND interval=?
        AND known_at_ms<=? ORDER BY fetch_id DESC LIMIT 1''',(symbol,interval,cutoff)).fetchone()
    watermark=c.execute('SELECT COALESCE(MAX(revision_id),0) FROM interval_revisions WHERE instrument_id=? AND interval=?',(iid,interval)).fetchone()[0]
    return dict(candles=[dict(timestamp=stamp(r['timestamp']),**{k:r[k] for k in ('open','high','low','close','volume')}) for r in rows],
        status=[dict(timestamp=stamp(r['timestamp']),session=r['session'],session_open=stamp(session_bounds(r['session'])[0]),
            session_close=stamp(session_bounds(r['session'])[1]),interval_end=stamp(r['interval_end']),
            available_minutes=None,expected_minutes=r['expected_minutes'],coverage_complete=True,interval_ended=True,
            volume_known=r['volume'] is not None,price_source=f'Yahoo {interval} history',source_resolution=interval,
            coverage_basis='provider interval bar') for r in rows],has_more=more,
        history_earliest=stamp(first[0]) if first else None,interval_watermark=watermark,history_fetch=dict(fetch) if fetch else None)
