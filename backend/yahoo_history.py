"""Versioned Yahoo minute bars, kept separate from received quote observations."""
from datetime import datetime, timedelta, timezone
from contextlib import closing
import hashlib
import json
import math
import sqlite3

import exchange_calendars as xc
import pandas as pd
import yfinance as yf


SCHEMA = '''
CREATE TABLE IF NOT EXISTS yahoo_minute_bars (
    bar_id INTEGER PRIMARY KEY, ticker TEXT NOT NULL, timestamp TEXT NOT NULL,
    fetched_at TEXT NOT NULL, snapshot_at TEXT NOT NULL, candle_json TEXT NOT NULL,
    completed INTEGER NOT NULL, payload_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS yahoo_bars_time ON yahoo_minute_bars(ticker, timestamp, bar_id);
CREATE TABLE IF NOT EXISTS yahoo_history_fetches (
    fetch_id INTEGER PRIMARY KEY, ticker TEXT NOT NULL, fetched_at TEXT NOT NULL,
    status TEXT NOT NULL, bar_count INTEGER NOT NULL, message TEXT
);
'''


def iso(time):
    return time.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def initialize(database):
    from backend.market_store import MarketRecorder
    with MarketRecorder(database):
        pass
    with closing(sqlite3.connect(database)) as connection:
        connection.executescript(SCHEMA)


def market_status(now=None):
    now = now or datetime.now(timezone.utc)
    calendar = xc.get_calendar('XNYS')
    date = pd.Timestamp(now.astimezone(timezone.utc).date())
    session = calendar.date_to_session(date, direction='previous')
    op, close = calendar.session_open(session), calendar.session_close(session)
    is_open = op <= pd.Timestamp(now) < close
    next_session = session if pd.Timestamp(now) < op else calendar.next_session(session)
    return {'status': 'open' if is_open else 'closed',
            'label': 'Market open' if is_open else 'Market closed',
            'session_open': iso(op), 'session_close': iso(close),
            'next_open': iso(calendar.session_open(next_session)), 'timezone': 'America/New_York'}


def save_bars(database, symbol, candles, fetched_at, snapshot_at=None):
    """Append revisions; an identical fetch never adds a second effective minute."""
    initialize(database)
    snapshot_at = snapshot_at or fetched_at
    with closing(sqlite3.connect(database)) as connection:
        connection.row_factory = sqlite3.Row
        from backend.candle_store import ingest_bar
        for candle in candles:
            start = datetime.fromisoformat(candle['timestamp'].replace('Z', '+00:00'))
            if start > snapshot_at:
                continue
            prices = [float(candle[key]) for key in ('open', 'high', 'low', 'close')]
            volume = candle['volume']
            if not all(math.isfinite(p) and p > 0 for p in prices):
                raise ValueError('Invalid Yahoo price')
            if volume is not None and (not math.isfinite(volume) or volume < 0 or int(volume) != volume):
                raise ValueError('Invalid Yahoo minute volume')
            if candle['high'] < max(candle['open'], candle['close'], candle['low']) or candle['low'] > min(candle['open'], candle['close']):
                raise ValueError('Invalid Yahoo OHLC range')
            encoded = json.dumps(candle, sort_keys=True, allow_nan=False)
            digest = hashlib.sha256(encoded.encode()).hexdigest()
            completed = int(start + timedelta(minutes=1) <= snapshot_at)
            # Compare with the latest version, allowing A -> B -> A revisions.
            prior = connection.execute('''SELECT payload_hash, completed FROM yahoo_minute_bars
                WHERE ticker=? AND timestamp=? ORDER BY bar_id DESC LIMIT 1''',
                (symbol, candle['timestamp'])).fetchone()
            if completed and prior and tuple(prior) == (digest, completed):
                continue
            connection.execute('''INSERT OR IGNORE INTO yahoo_minute_bars
                (ticker,timestamp,fetched_at,snapshot_at,candle_json,completed,payload_hash)
                VALUES (?,?,?,?,?,?,?)''', (symbol, candle['timestamp'], iso(fetched_at),
                iso(snapshot_at), encoded, completed, digest))
            bar = connection.execute('SELECT * FROM yahoo_minute_bars WHERE bar_id=last_insert_rowid()').fetchone()
            ingest_bar(connection,bar)
        connection.commit()


def fetch_recent(database, symbol='AAPL', start=None, download_only=False):
    initialize(database)
    started = datetime.now(timezone.utc)
    try:
        query = {'start':start} if start else {'period':'5d'}
        frame = yf.Ticker(symbol).history(**query, interval='1m', prepost=False,
                                         auto_adjust=False, actions=False, timeout=10)
        if frame.empty:
            raise ValueError('Yahoo returned no minute bars')
        candles = []
        for timestamp, row in frame.iterrows():
            if row[['Open', 'High', 'Low', 'Close']].isna().any():
                continue
            candles.append(dict(timestamp=iso(timestamp), open=float(row.Open), high=float(row.High),
                                low=float(row.Low), close=float(row.Close),
                                volume=None if pd.isna(row.Volume) else int(row.Volume)))
        if not candles:
            raise ValueError('Yahoo returned no usable minute bars')
        fetched = datetime.now(timezone.utc)
        if not download_only:
            save_bars(database, symbol, candles, fetched, started)
        status, message = 'ok', None
    except Exception as error:
        candles = []
        fetched = datetime.now(timezone.utc)
        status, message = 'unavailable', f'Yahoo minute history unavailable ({type(error).__name__}); using saved data.'
    if download_only:
        return dict(status=status,bar_count=len(candles),message=message,candles=candles,fetched=fetched,started=started)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute('''INSERT INTO yahoo_history_fetches
            (ticker,fetched_at,status,bar_count,message) VALUES (?,?,?,?,?)''',
            (symbol, iso(fetched), status, len(candles), message))
        connection.commit()
    return {'status': status, 'bar_count': len(candles), 'message': message}


def persist_download(database, symbol, result):
    if result['status']=='ok':
        save_bars(database,symbol,result['candles'],result['fetched'],result['started'])
    with closing(sqlite3.connect(database)) as c:
        c.execute('INSERT INTO yahoo_history_fetches(ticker,fetched_at,status,bar_count,message) VALUES (?,?,?,?,?)',
                  (symbol,iso(result['fetched']),result['status'],result['bar_count'],result['message']))
        c.commit()


def available_bars(connection, symbol, now):
    rows = connection.execute('''SELECT timestamp, candle_json, completed, snapshot_at, fetched_at
        FROM yahoo_minute_bars WHERE ticker=? AND julianday(fetched_at)<=julianday(?)
        ORDER BY bar_id''', (symbol, iso(now))).fetchall()
    return {row['timestamp']: dict(row) for row in rows}
