"""Indexed current candles and append-only changed revisions. No whole-store tick scans."""
from datetime import datetime, timezone, timedelta
from functools import lru_cache
from contextlib import nullcontext
import json
import sqlite3

SCHEMA = '''
CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS instruments(instrument_id INTEGER PRIMARY KEY, symbol TEXT UNIQUE NOT NULL,
    calendar TEXT NOT NULL DEFAULT 'XNYS', timezone TEXT NOT NULL DEFAULT 'America/New_York');
CREATE TABLE IF NOT EXISTS candles_1m(instrument_id INTEGER NOT NULL, minute_start INTEGER NOT NULL,
    open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL, volume INTEGER,
    complete INTEGER NOT NULL, source TEXT NOT NULL, session TEXT NOT NULL, revision_id INTEGER NOT NULL,
    updated_ms INTEGER NOT NULL, PRIMARY KEY(instrument_id,minute_start)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS candle_forming ON candles_1m(complete,minute_start);
CREATE TABLE IF NOT EXISTS candle_revisions(revision_id INTEGER PRIMARY KEY, instrument_id INTEGER NOT NULL,
    minute_start INTEGER NOT NULL, open REAL, high REAL, low REAL, close REAL, volume INTEGER,
    complete INTEGER NOT NULL, source TEXT NOT NULL, session TEXT NOT NULL, known_at_ms INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS revision_minute ON candle_revisions(instrument_id,minute_start,known_at_ms,revision_id);
CREATE INDEX IF NOT EXISTS revision_changes ON candle_revisions(instrument_id,revision_id);
CREATE TABLE IF NOT EXISTS candle_provenance(revision_id INTEGER PRIMARY KEY REFERENCES candle_revisions(revision_id),
    source_kind TEXT NOT NULL, source_reference TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS yahoo_minute_values(bar_id INTEGER PRIMARY KEY, instrument_id INTEGER NOT NULL,
    minute_start INTEGER NOT NULL, open REAL, high REAL, low REAL, close REAL, volume INTEGER,
    complete INTEGER NOT NULL, known_at_ms INTEGER NOT NULL, snapshot_ms INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS minute_bar ON yahoo_minute_values(instrument_id,minute_start,bar_id);
CREATE TABLE IF NOT EXISTS ingestion_state(instrument_id INTEGER PRIMARY KEY, last_receipt_id INTEGER NOT NULL DEFAULT 0,
    last_source_ms INTEGER, reconciled_ms INTEGER);
'''

from backend.daily_history import SCHEMA as DAILY_SCHEMA
from backend.interval_history import SCHEMA as INTERVAL_SCHEMA
SCHEMA += DAILY_SCHEMA + INTERVAL_SCHEMA


def epoch(value):
    return round(datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()*1000)


def stamp(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def instrument(c, symbol):
    c.execute('INSERT OR IGNORE INTO instruments(symbol) VALUES (?)', (symbol,))
    return c.execute('SELECT instrument_id FROM instruments WHERE symbol=?', (symbol,)).fetchone()[0]


@lru_cache(maxsize=4096)
def session_bounds(day):
    import exchange_calendars as xc
    cal = xc.get_calendar('XNYS')
    if not cal.is_session(day):
        return None
    return int(cal.session_open(day).timestamp()), int(cal.session_close(day).timestamp())


def session_for(start):
    day = stamp(start)[:10]
    bounds = session_bounds(day)
    return day if bounds and bounds[0] <= start < bounds[1] else None


def initialize(c):
    c.executescript(SCHEMA)
    if c.execute('SELECT 1 FROM schema_migrations WHERE version=1').fetchone():
        if not c.execute('SELECT 1 FROM schema_migrations WHERE version=2').fetchone():
            with c:
                c.execute('''INSERT OR IGNORE INTO candle_provenance
                    SELECT r.revision_id,r.source,'bar:'||b.bar_id FROM candle_revisions r JOIN yahoo_minute_values b
                    ON b.bar_id=(SELECT MAX(x.bar_id) FROM yahoo_minute_values x WHERE x.instrument_id=r.instrument_id
                        AND x.minute_start=r.minute_start AND x.known_at_ms<=r.known_at_ms)''')
                c.execute('INSERT INTO schema_migrations VALUES (2,?)',(datetime.now(timezone.utc).isoformat(),))
        if not c.execute('SELECT 1 FROM schema_migrations WHERE version=3').fetchone():
            with c:
                c.execute('INSERT OR IGNORE INTO schema_migrations VALUES (3,?)',(datetime.now(timezone.utc).isoformat(),))
        if not c.execute('SELECT 1 FROM schema_migrations WHERE version=4').fetchone():
            with c:
                c.execute('INSERT OR IGNORE INTO schema_migrations VALUES (4,?)',(datetime.now(timezone.utc).isoformat(),))
        return
    with c:
        for table, column, sql_type in [('observations','instrument_id','INTEGER'),
                ('receipts','instrument_id','INTEGER'), ('receipts','receipt_ms','INTEGER')]:
            if column not in {r[1] for r in c.execute(f'PRAGMA table_info({table})')}:
                c.execute(f'ALTER TABLE {table} ADD COLUMN {column} {sql_type}')
        for row in c.execute('SELECT DISTINCT ticker FROM observations').fetchall():
            iid = instrument(c, row[0])
            c.execute('UPDATE observations SET instrument_id=? WHERE ticker=?', (iid,row[0]))
        c.execute('''UPDATE receipts SET instrument_id=(SELECT instrument_id FROM observations o WHERE o.observation_id=receipts.observation_id),
            receipt_ms=CAST(round((julianday(backend_receipt_time_utc)-2440587.5)*86400000) AS INTEGER)''')
        c.execute('CREATE INDEX IF NOT EXISTS obs_minute ON observations(instrument_id,source_time_epoch_ms,observation_id)')
        c.execute('CREATE INDEX IF NOT EXISTS obs_supersedes ON observations(supersedes_observation_id)')
        c.execute('CREATE INDEX IF NOT EXISTS receipt_replay ON receipts(instrument_id,receipt_id)')
        c.execute('CREATE INDEX IF NOT EXISTS receipt_available ON receipts(observation_id,receipt_ms)')
        c.execute('''CREATE TRIGGER IF NOT EXISTS observation_instrument AFTER INSERT ON observations BEGIN
            INSERT OR IGNORE INTO instruments(symbol) VALUES (NEW.ticker);
            UPDATE observations SET instrument_id=(SELECT instrument_id FROM instruments WHERE symbol=NEW.ticker) WHERE observation_id=NEW.observation_id; END''')
        c.execute('''CREATE TRIGGER IF NOT EXISTS receipt_integer_time AFTER INSERT ON receipts BEGIN
            UPDATE receipts SET instrument_id=(SELECT instrument_id FROM observations WHERE observation_id=NEW.observation_id),
            receipt_ms=CAST(round((julianday(NEW.backend_receipt_time_utc)-2440587.5)*86400000) AS INTEGER) WHERE receipt_id=NEW.receipt_id; END''')
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'yahoo_minute_bars' in tables:
            for bar in c.execute('SELECT * FROM yahoo_minute_bars ORDER BY bar_id').fetchall():
                ingest_bar(c, bar, refresh=False)
        events = c.execute('''SELECT o.instrument_id, o.source_time_epoch_ms/60000*60 AS minute_start, r.receipt_ms AS known
            FROM receipts r JOIN observations o USING(observation_id) WHERE o.source_time_epoch_ms IS NOT NULL
            UNION ALL SELECT instrument_id,minute_start,known_at_ms FROM yahoo_minute_values ORDER BY known''').fetchall()
        for iid, start, known in events:
            for minute in (start-60,start,start+60):
                refresh_minute(c,iid,int(minute),known)
        now = datetime.now(timezone.utc)
        finish_minutes(c, now,commit=False)
        c.execute('INSERT INTO schema_migrations VALUES (1,?)', (now.isoformat(),))
        c.execute('INSERT INTO schema_migrations VALUES (2,?)', (now.isoformat(),))
        c.execute('INSERT INTO schema_migrations VALUES (3,?)', (now.isoformat(),))
        c.execute('INSERT INTO schema_migrations VALUES (4,?)', (now.isoformat(),))


def ingest_bar(c, bar, refresh=True):
    candle = json.loads(bar['candle_json'])
    iid = instrument(c, bar['ticker'])
    start = epoch(candle['timestamp'])//1000
    known = epoch(bar['fetched_at'])
    c.execute('''INSERT OR IGNORE INTO yahoo_minute_values VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
        (bar['bar_id'],iid,start,*[candle[k] for k in ('open','high','low','close','volume')],
         bar['completed'],known,epoch(bar['snapshot_at'])))
    if refresh:
        refresh_minute(c,iid,start,known)


def refresh_minute(c, iid, start, now_ms):
    session = session_for(start)
    if session is None:
        return
    rows = c.execute('''SELECT o.* FROM observations o WHERE instrument_id=?
        AND source_time_epoch_ms>=? AND source_time_epoch_ms<? AND price IS NOT NULL
        AND EXISTS(SELECT 1 FROM receipts r WHERE r.observation_id=o.observation_id AND receipt_ms<=?)
        AND NOT EXISTS(SELECT 1 FROM observations x JOIN receipts r ON r.observation_id=x.observation_id
            WHERE x.supersedes_observation_id=o.observation_id AND r.receipt_ms<=?)
        ORDER BY source_time_epoch_ms,observation_id''', (iid,(start-60)*1000,(start+60)*1000,now_ms,now_ms)).fetchall()
    inside = [r for r in rows if r['source_time_epoch_ms']>=start*1000]
    baseline = next((r['day_volume'] for r in reversed(rows) if r['source_time_epoch_ms']<start*1000
                     and r['day_volume'] is not None and stamp(r['source_time_epoch_ms']//1000)[:10]==session),None)
    candle = None
    source = 'Yahoo WebSocket observations'
    if inside:
        prices = [r['price'] for r in inside]
        totals = [r['day_volume'] for r in inside if r['day_volume'] is not None]
        sequence = [baseline, *totals]
        volume = totals[-1]-baseline if baseline is not None and totals and all(b>=a for a,b in zip(sequence,sequence[1:])) else None
        candle = (prices[0],max(prices),min(prices),prices[-1],volume)
    bar = c.execute('''SELECT * FROM yahoo_minute_values WHERE instrument_id=? AND minute_start=? AND known_at_ms<=?
                       ORDER BY bar_id DESC LIMIT 1''', (iid,start,now_ms)).fetchone()
    if bar:
        candle = tuple(bar[k] for k in ('open','high','low','close','volume'))
        source = 'Yahoo minute history'
        if not bar['complete']:
            newer = [r for r in inside if r['source_time_epoch_ms']>bar['snapshot_ms']]
            if newer:
                candle = (candle[0],max(candle[1],*[r['price'] for r in newer]),
                          min(candle[2],*[r['price'] for r in newer]),newer[-1]['price'],None)
                source = 'Yahoo provisional minute + observations'
    if candle is None:
        return
    complete = int(now_ms>=(start+60)*1000)
    old = c.execute('SELECT * FROM candles_1m WHERE instrument_id=? AND minute_start=?',(iid,start)).fetchone()
    state = (*candle,complete,source,session)
    if old and tuple(old[k] for k in ('open','high','low','close','volume','complete','source','session')) == state:
        return
    revision = c.execute('''INSERT INTO candle_revisions(instrument_id,minute_start,open,high,low,close,volume,
        complete,source,session,known_at_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?)''', (iid,start,*state,now_ms)).lastrowid
    reference = ('bar:'+str(bar['bar_id'])) if bar else 'observations:'+','.join(str(row['observation_id']) for row in inside)
    c.execute('INSERT INTO candle_provenance VALUES (?,?,?)',(revision,source,reference))
    c.execute('''INSERT INTO candles_1m VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(instrument_id,minute_start)
        DO UPDATE SET open=excluded.open,high=excluded.high,low=excluded.low,close=excluded.close,volume=excluded.volume,
        complete=excluded.complete,source=excluded.source,session=excluded.session,revision_id=excluded.revision_id,updated_ms=excluded.updated_ms''',
        (iid,start,*state,revision,now_ms))


def record_effect(c, symbol, result, source_ms, receipt_ms):
    iid = instrument(c,symbol)
    with c:
        c.execute('''INSERT INTO ingestion_state(instrument_id,last_receipt_id,last_source_ms) VALUES (?,?,?)
            ON CONFLICT(instrument_id) DO UPDATE SET last_receipt_id=excluded.last_receipt_id,
            last_source_ms=MAX(COALESCE(ingestion_state.last_source_ms,0),COALESCE(excluded.last_source_ms,0))''',(iid,result.receipt_id,source_ms))
        if not result.is_exact_repeat and source_ms is not None:
            start = source_ms//60000*60
            for minute in (start-60,start,start+60):
                refresh_minute(c,iid,minute,receipt_ms)


def finish_minutes(c, now,commit=True):
    now_ms = round(now.timestamp()*1000)
    with c if commit else nullcontext():
        for row in c.execute('SELECT instrument_id,minute_start FROM candles_1m WHERE complete=0 AND minute_start<=?',(now_ms//1000-60,)).fetchall():
            refresh_minute(c,row[0],row[1],now_ms)


def candle_dict(row):
    return dict(timestamp=stamp(row['minute_start']), **{k:row[k] for k in ('open','high','low','close','volume')})


def read_minutes(c, symbol, limit=2000, before=None, start=None, as_of=None):
    iidrow = c.execute('SELECT instrument_id FROM instruments WHERE symbol=?',(symbol,)).fetchone()
    if not iidrow:
        return []
    iid = iidrow[0]
    end = epoch(before)//1000 if before else 2**62
    begin = epoch(start)//1000 if start else 0
    if as_of is None:
        return c.execute('''SELECT * FROM candles_1m WHERE instrument_id=? AND minute_start>=? AND minute_start<?
            ORDER BY minute_start DESC LIMIT ?''',(iid,begin,end,limit)).fetchall()[::-1]
    cutoff = round(as_of.timestamp()*1000)
    return c.execute('''SELECT * FROM candle_revisions r WHERE instrument_id=? AND minute_start>=? AND minute_start<? AND known_at_ms<=?
        AND revision_id=(SELECT MAX(x.revision_id) FROM candle_revisions x WHERE x.instrument_id=r.instrument_id
            AND x.minute_start=r.minute_start AND x.known_at_ms<=?) ORDER BY minute_start DESC LIMIT ?''',
        (iid,begin,end,cutoff,cutoff,limit)).fetchall()[::-1]
