"""Version-5 backtest-only tables; no foreign keys to live accounts/orders."""
from contextlib import closing
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sqlite3
from threading import RLock

from backend.backtesting import MAX_BARS, MAX_EVENTS, digest, settings, text, utc

SCHEMA = '''
CREATE TABLE IF NOT EXISTS backtest_datasets (
 dataset_hash TEXT PRIMARY KEY, dataset_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS backtest_runs (
 run_id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE, request_hash TEXT NOT NULL,
 created_at TEXT NOT NULL, dataset_hash TEXT NOT NULL REFERENCES backtest_datasets(dataset_hash),
 settings_json TEXT NOT NULL, summary_json TEXT NOT NULL, result_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS backtest_orders (
 run_id TEXT NOT NULL REFERENCES backtest_runs(run_id), order_id INTEGER NOT NULL, order_json TEXT NOT NULL,
 PRIMARY KEY(run_id,order_id)
);
CREATE TABLE IF NOT EXISTS backtest_decisions (
 run_id TEXT NOT NULL REFERENCES backtest_runs(run_id), sequence INTEGER NOT NULL, decision_json TEXT NOT NULL,
 PRIMARY KEY(run_id,sequence)
);
CREATE TABLE IF NOT EXISTS backtest_equity (
 run_id TEXT NOT NULL REFERENCES backtest_runs(run_id), sequence INTEGER NOT NULL, row_json TEXT NOT NULL,
 PRIMARY KEY(run_id,sequence)
);
CREATE INDEX IF NOT EXISTS backtest_created ON backtest_runs(created_at,run_id);
'''


class RequestConflict(ValueError):
    pass


def load_dataset(database, config):
    """Freeze only existing data; no Yahoo/model calls or source writes."""
    config = settings(config)
    frozen = utc(config['frozen_at']) if config['frozen_at'] else datetime.now(timezone.utc)
    if frozen > datetime.now(timezone.utc):
        raise ValueError('Frozen data vintage cannot be in the future.')
    if frozen < utc(config['end']):
        raise ValueError('Backtest end must not exceed the frozen data vintage.')
    config['frozen_at'] = text(frozen)
    dataset = dict(version=1, symbol=config['symbol'], timeframe=config['timeframe'],
                   data_mode=config['data_mode'], frozen_at=text(frozen), bars=[], prices=[],
                   provenance=dict(storage='local immutable SQLite read snapshot',
                                   adjustment_policy='as-stored OHLC; Yahoo imports use unadjusted prices',
                                   source='saved revisions only; no downloads'))
    # A single read-only transaction freezes warm-up/range/revision reads without
    # copying the whole database or opening the live paper account.
    from backend.recorded_history import recorded_history
    from backend.candle_store import stamp
    path = Path(database).resolve()
    with closing(sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True)) as snapshot:
        snapshot.row_factory = sqlite3.Row
        snapshot.execute('BEGIN')
        if config['data_mode'] == 'historical_bars':
            # Reuse source precedence/calendar aggregation through the read-only connection.
            warm = recorded_history(path, config['symbol'], config['timeframe'], frozen,
                                    limit=config['slow_window']+1, before=config['start'], apply_policy=False, connection=snapshot)
            page = recorded_history(path, config['symbol'], config['timeframe'], frozen,
                                    limit=MAX_BARS+1, before=config['end'], start=config['start'], apply_policy=False, connection=snapshot)
            if len(page['candles']) > MAX_BARS or page['next_before']:
                raise ValueError('Stored range exceeds the 10000-candle limit; select a shorter range.')
            flags = {item['timestamp']: item for item in warm['status']+page['status']}
            for candle in warm['candles']+page['candles']:
                flag = flags[candle['timestamp']]
                beginning = utc(candle['timestamp'])
                minutes = {'1m':1,'5m':5,'15m':15,'1h':60,'1d':1440}[config['timeframe']]
                finish = utc(flag['interval_end']) if flag.get('interval_end') else beginning + timedelta(minutes=minutes)
                if flag.get('session_close'):
                    finish = min(finish, utc(flag['session_close']))
                dataset['bars'].append(dict(candle, end_time=text(finish), available_at=text(finish),
                    complete=bool(flag['interval_ended']), coverage_complete=bool(flag['coverage_complete']),
                    source=flag.get('price_source', 'saved minute aggregation')))
            dataset['provenance']['availability'] = 'assumed at bar close on a fixed data vintage; original revision knowledge is not reconstructed'
        else:
            iid = snapshot.execute('SELECT instrument_id FROM instruments WHERE symbol=?',(config['symbol'],)).fetchone()
            if not iid:
                raise ValueError('No recorded data for this ticker.')
            iid = iid[0]
            start, end = int(utc(config['start']).timestamp()), int(utc(config['end']).timestamp())
            prior = snapshot.execute('''SELECT DISTINCT minute_start FROM candle_revisions
                WHERE instrument_id=? AND minute_start<? AND known_at_ms<=?
                ORDER BY minute_start DESC LIMIT ?''',(iid,start,end*1000,config['slow_window']+1)).fetchall()
            lower = prior[-1][0] if prior else start
            rows = snapshot.execute('''SELECT * FROM candle_revisions WHERE instrument_id=?
                AND minute_start>=? AND minute_start<? AND known_at_ms<=?
                ORDER BY known_at_ms,revision_id LIMIT ?''',(iid,lower,end,end*1000,MAX_EVENTS+1)).fetchall()
            prices = snapshot.execute('''SELECT r.receipt_id,r.receipt_ms,o.observation_id,o.price FROM receipts r
                JOIN observations o USING(observation_id) WHERE r.instrument_id=? AND r.receipt_ms>=?
                AND r.receipt_ms<? AND o.price>0 ORDER BY r.receipt_ms,r.receipt_id LIMIT ?''',
                (iid,start*1000,end*1000,MAX_EVENTS+1)).fetchall()
            if len(rows)+len(prices) > MAX_EVENTS:
                raise ValueError('Recorded range exceeds 50000 events; select a shorter range.')
            for row in rows:
                dataset['bars'].append(dict(timestamp=stamp(row['minute_start']),end_time=stamp(row['minute_start']+60),
                    available_at=text(datetime.fromtimestamp(row['known_at_ms']/1000,timezone.utc)),
                    **{key:row[key] for key in ('open','high','low','close','volume')},
                    complete=bool(row['complete']),coverage_complete=True,source=row['source'],reference=f'revision:{row["revision_id"]}'))
            dataset['prices'] = [dict(event_id=f'receipt:{row["receipt_id"]}',price=row['price'],
                available_at=text(datetime.fromtimestamp(row['receipt_ms']/1000,timezone.utc)),
                observation_id=row['observation_id'],receipt_id=row['receipt_id']) for row in prices]
            dataset['provenance']['availability'] = 'recorded revision known_at_ms and actual receipt availability; same-time quotes precede decisions'
    return config, dataset


class BacktestStore:
    def __init__(self, database):
        self.connection = sqlite3.connect(database, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute('PRAGMA foreign_keys=ON')
        self.lock = RLock()

    def close(self):
        self.connection.close()

    def existing(self, request_id, request_hash):
        with self.lock:
            row = self.connection.execute('SELECT request_hash,result_json FROM backtest_runs WHERE request_id=?',(request_id,)).fetchone()
            if not row:
                return None
            if row['request_hash'] != request_hash:
                raise RequestConflict('Request ID already belongs to different backtest settings.')
            return json.loads(row['result_json'])

    def save(self, request_id, request_hash, dataset, result):
        if digest(dataset) != result['dataset_hash']:
            raise ValueError('Backtest dataset hash mismatch.')
        with self.lock, self.connection:
            previous = self.existing(request_id,request_hash)
            if previous:
                return previous
            encoded = lambda value: json.dumps(value, sort_keys=True, allow_nan=False)
            self.connection.execute('INSERT OR IGNORE INTO backtest_datasets VALUES (?,?)',(result['dataset_hash'],encoded(dataset)))
            self.connection.execute('INSERT INTO backtest_runs VALUES (?,?,?,?,?,?,?,?)',
                (result['run_id'],request_id,request_hash,text(datetime.now(timezone.utc)),result['dataset_hash'],
                 encoded(result['settings']),encoded(result['summary']),encoded(result)))
            self.connection.executemany('INSERT INTO backtest_orders VALUES (?,?,?)',
                [(result['run_id'],row['order_id'],encoded(row)) for row in result['orders']])
            for table, field in (('backtest_decisions','decisions'),('backtest_equity','equity')):
                self.connection.executemany(f'INSERT INTO {table} VALUES (?,?,?)',
                    [(result['run_id'],index,encoded(row)) for index,row in enumerate(result[field])])
        return result

    def get(self, run_id):
        with self.lock:
            row = self.connection.execute('SELECT result_json FROM backtest_runs WHERE run_id=?',(run_id,)).fetchone()
            if not row:
                raise KeyError(run_id)
            return json.loads(row[0])

    def dataset(self, run_id):
        with self.lock:
            row = self.connection.execute('''SELECT d.dataset_hash,d.dataset_json FROM backtest_runs r
                JOIN backtest_datasets d USING(dataset_hash) WHERE run_id=?''',(run_id,)).fetchone()
            if not row:
                raise KeyError(run_id)
            dataset = json.loads(row['dataset_json'])
            if digest(dataset) != row['dataset_hash']:
                raise ValueError('Stored dataset failed its integrity check.')
            return dataset

    def list(self, limit=20, offset=0):
        with self.lock:
            return [dict(run_id=row['run_id'],created_at=row['created_at'],dataset_hash=row['dataset_hash'],
                         settings=json.loads(row['settings_json']),summary=json.loads(row['summary_json']))
                    for row in self.connection.execute('SELECT * FROM backtest_runs ORDER BY created_at DESC,run_id LIMIT ? OFFSET ?',(limit,offset))]
