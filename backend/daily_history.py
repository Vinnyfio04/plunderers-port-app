"""Full Yahoo daily history, separate from the short-retention minute feed."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math

import exchange_calendars as xc
import pandas as pd
import yfinance as yf


SCHEMA = '''
CREATE TABLE IF NOT EXISTS daily_candles (
    instrument_id INTEGER NOT NULL, timestamp INTEGER NOT NULL, session TEXT NOT NULL,
    session_close INTEGER NOT NULL, open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL,
    close REAL NOT NULL, volume INTEGER, expected_minutes INTEGER NOT NULL,
    known_at_ms INTEGER NOT NULL, revision_id INTEGER NOT NULL,
    PRIMARY KEY(instrument_id,timestamp)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS daily_revisions (
    revision_id INTEGER PRIMARY KEY, instrument_id INTEGER NOT NULL, timestamp INTEGER NOT NULL,
    session TEXT NOT NULL, session_close INTEGER NOT NULL, open REAL NOT NULL, high REAL NOT NULL,
    low REAL NOT NULL, close REAL NOT NULL, volume INTEGER, expected_minutes INTEGER NOT NULL,
    known_at_ms INTEGER NOT NULL, payload_hash TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS daily_revision_time ON daily_revisions(instrument_id,timestamp,known_at_ms,revision_id);
CREATE INDEX IF NOT EXISTS daily_revision_changes ON daily_revisions(instrument_id,revision_id);
CREATE TABLE IF NOT EXISTS daily_history_fetches (
    fetch_id INTEGER PRIMARY KEY, ticker TEXT NOT NULL, fetched_at TEXT NOT NULL, known_at_ms INTEGER NOT NULL,
    status TEXT NOT NULL, bar_count INTEGER NOT NULL, message TEXT);
CREATE INDEX IF NOT EXISTS daily_fetch_symbol ON daily_history_fetches(ticker,fetch_id);
'''


def refresh_needed(database, symbol, now=None):
    from backend.market_store import MarketRecorder
    now = now or datetime.now(timezone.utc)
    with MarketRecorder(database) as store:
        c = store.connection
        last = c.execute('SELECT * FROM daily_history_fetches WHERE ticker=? ORDER BY fetch_id DESC LIMIT 1',(symbol,)).fetchone()
        if last:
            age = (now-datetime.fromisoformat(last['fetched_at'].replace('Z','+00:00'))).total_seconds()
            if age < 60:
                return False
            latest_row = c.execute('''SELECT session FROM daily_candles
                WHERE instrument_id=(SELECT instrument_id FROM instruments WHERE symbol=?) ORDER BY timestamp DESC LIMIT 1''',(symbol,)).fetchone()
            latest = latest_row[0] if latest_row else None
            cal = xc.get_calendar('XNYS')
            session = cal.date_to_session(pd.Timestamp(now.date()),direction='previous')
            if cal.session_close(session)>pd.Timestamp(now):
                session = cal.previous_session(session)
            if last['status']=='ok' and age<86400 and latest and latest>=str(session.date()):
                return False
    return True


def download(symbol):
    """Fetch all available completed sessions; never fabricate old one-minute data."""
    started = datetime.now(timezone.utc)
    try:
        frame = yf.Ticker(symbol).history(period='max',interval='1d',prepost=False,
            auto_adjust=False,actions=False,timeout=10)
        if frame.empty:
            raise ValueError('Yahoo returned no daily history')
        frame = frame.sort_index()
        cal = xc.get_calendar('XNYS',start=str(frame.index[0].date()),end=str((started+timedelta(days=1)).date()))
        candles = []
        for date,row in frame.iterrows():
            day = str(date.date())
            if not cal.is_session(day) or row[['Open','High','Low','Close']].isna().any():
                continue
            opening,closing = cal.session_open(day),cal.session_close(day)
            if closing>pd.Timestamp(started):
                continue  # The forming day continues to use the real minute aggregation.
            prices = tuple(float(row[k]) for k in ('Open','High','Low','Close'))
            volume = None if pd.isna(row.Volume) else float(row.Volume)
            if (not all(math.isfinite(p) and p>0 for p in prices)
                    or prices[1]<max(prices) or prices[2]>min(prices)
                    or (volume is not None and (not math.isfinite(volume) or volume<0 or not volume.is_integer()))):
                raise ValueError('Invalid Yahoo daily OHLCV')
            candles.append((int(opening.timestamp()),day,int(closing.timestamp()),*prices,
                            None if volume is None else int(volume),int((closing-opening).total_seconds()//60)))
        if not candles:
            raise ValueError('Yahoo returned no completed daily candles')
        return dict(status='ok',message=None,candles=candles,fetched=datetime.now(timezone.utc))
    except Exception as error:
        return dict(status='unavailable',candles=[],fetched=datetime.now(timezone.utc),
            message=f'Full Yahoo daily history unavailable ({type(error).__name__}); keeping saved candles.')


def persist(database, symbol, result):
    from backend.market_store import MarketRecorder
    from backend.candle_store import instrument
    known = round(result['fetched'].timestamp()*1000)
    with MarketRecorder(database) as store:
        c = store.connection
        with c:
            iid = instrument(c,symbol)
            for row in result['candles']:
                digest = hashlib.sha256(json.dumps(row,allow_nan=False).encode()).hexdigest()
                prior = c.execute('''SELECT payload_hash FROM daily_revisions
                    WHERE instrument_id=? AND timestamp=? ORDER BY revision_id DESC LIMIT 1''',(iid,row[0])).fetchone()
                if prior and prior[0]==digest:
                    continue
                revision = c.execute('''INSERT INTO daily_revisions
                    (instrument_id,timestamp,session,session_close,open,high,low,close,volume,expected_minutes,known_at_ms,payload_hash)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',(iid,*row,known,digest)).lastrowid
                c.execute('''INSERT INTO daily_candles VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(instrument_id,timestamp) DO UPDATE SET session=excluded.session,
                    session_close=excluded.session_close,open=excluded.open,high=excluded.high,low=excluded.low,
                    close=excluded.close,volume=excluded.volume,expected_minutes=excluded.expected_minutes,
                    known_at_ms=excluded.known_at_ms,revision_id=excluded.revision_id''',(iid,*row,known,revision))
            c.execute('INSERT INTO daily_history_fetches(ticker,fetched_at,known_at_ms,status,bar_count,message) VALUES (?,?,?,?,?,?)',
                (symbol,result['fetched'].isoformat().replace('+00:00','Z'),known,result['status'],len(result['candles']),result['message']))


def page(c, symbol, limit, before=None, start=None, as_of=None):
    from backend.candle_store import epoch,stamp
    cutoff = round((as_of or datetime.now(timezone.utc)).timestamp()*1000)
    end,begin = epoch(before)//1000 if before else 2**62,epoch(start)//1000 if start else -(2**62)
    iid = c.execute('SELECT instrument_id FROM instruments WHERE symbol=?',(symbol,)).fetchone()
    if not iid:
        return None
    iid = iid[0]
    table = 'daily_revisions' if as_of else 'daily_candles'
    extra = '''AND revision_id=(SELECT MAX(x.revision_id) FROM daily_revisions x
        WHERE x.instrument_id=b.instrument_id AND x.timestamp=b.timestamp AND x.known_at_ms<=?)''' if as_of else ''
    args = (iid,begin,end,cutoff,cutoff//1000)+((cutoff,) if as_of else ())+(limit+1,)
    rows = c.execute(f'''SELECT * FROM {table} b WHERE instrument_id=? AND timestamp>=? AND timestamp<?
        AND known_at_ms<=? AND session_close<=? {extra} ORDER BY timestamp DESC LIMIT ?''',args).fetchall()
    more = len(rows)>limit
    rows = rows[:limit][::-1]
    if as_of:
        bounds = c.execute('SELECT MIN(timestamp),MAX(timestamp) FROM daily_revisions WHERE instrument_id=? AND known_at_ms<=?',(iid,cutoff)).fetchone()
    else:
        first = c.execute('SELECT timestamp FROM daily_candles WHERE instrument_id=? ORDER BY timestamp LIMIT 1',(iid,)).fetchone()
        last = c.execute('SELECT timestamp FROM daily_candles WHERE instrument_id=? ORDER BY timestamp DESC LIMIT 1',(iid,)).fetchone()
        bounds = (first[0] if first else None,last[0] if last else None)
    watermark = c.execute('SELECT COALESCE(MAX(revision_id),0) FROM daily_revisions WHERE instrument_id=?',(iid,)).fetchone()[0]
    fetch = c.execute('SELECT status,fetched_at,message FROM daily_history_fetches WHERE ticker=? AND known_at_ms<=? ORDER BY fetch_id DESC LIMIT 1',(symbol,cutoff)).fetchone()
    return dict(candles=[dict(timestamp=stamp(r['timestamp']),**{k:r[k] for k in ('open','high','low','close','volume')}) for r in rows],
        status=[dict(timestamp=stamp(r['timestamp']),session=r['session'],session_open=stamp(r['timestamp']),
            session_close=stamp(r['session_close']),available_minutes=None,expected_minutes=r['expected_minutes'],
            coverage_complete=True,interval_ended=True,volume_known=r['volume'] is not None,
            price_source='Yahoo daily history',source_resolution='1d',coverage_basis='provider session bar') for r in rows],
        has_more=more,daily_earliest=stamp(bounds[0]) if bounds[0] is not None else None,
        daily_latest=stamp(bounds[1]) if bounds[1] is not None else None,
        daily_watermark=watermark,daily_fetch=dict(fetch) if fetch else None)


def oldest_page_before(database, symbol, limit):
    from backend.market_store import MarketRecorder
    from backend.candle_store import stamp
    with MarketRecorder(database) as store:
        row = store.connection.execute('''SELECT timestamp FROM daily_candles
            WHERE instrument_id=(SELECT instrument_id FROM instruments WHERE symbol=?)
            ORDER BY timestamp LIMIT 1 OFFSET ?''',(symbol,limit)).fetchone()
    return stamp(row[0]) if row else None
