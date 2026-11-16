"""Canonical database path, non-destructive migration, and local process ownership."""
import argparse
from contextlib import closing
import os
from pathlib import Path
import sqlite3

DATA = Path(__file__).resolve().parent / 'data'
DEFAULT_DATABASE = DATA / 'market.db'
LEGACY_DATABASE = DATA / 'market-observations.sqlite3'


def database_path():
    return Path(os.getenv('MARKET_DATABASE', str(DEFAULT_DATABASE))).expanduser().resolve()


class DatabaseOwner:
    def __init__(self, path):
        self.file = open(str(path) + '.lock', 'a+b')
        self.file.seek(0)
        self.file.write(b'0')
        self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError('Another backend owns this database; use one Uvicorn worker.') from None

    def close(self):
        self.file.close()


def prepare_database(target=None, legacy=None):
    target = Path(target or database_path())
    legacy = Path(legacy) if legacy else (LEGACY_DATABASE if target == DEFAULT_DATABASE else None)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        with closing(sqlite3.connect(target)) as current:
            tables = {r[0] for r in current.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if tables and 'observations' not in tables:
                raise RuntimeError('Existing market.db is not a recognized project store; refusing to overwrite or merge it.')
            if 'schema_migrations' in tables:
                version = current.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]
                if version and version>4:
                    raise RuntimeError('Database schema is newer than this backend')
    if not target.exists() and legacy and legacy.exists():
        temporary = Path(str(target) + '.migration')
        # A prior incomplete copy is safe to replace; the source is retained.
        if temporary.exists():
            temporary.unlink()
        with closing(sqlite3.connect(f'file:{legacy.as_posix()}?mode=ro', uri=True)) as source:
            with closing(sqlite3.connect(temporary)) as destination:
                source.backup(destination)
                if destination.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Migration copy failed integrity check')
                if destination.execute('PRAGMA foreign_key_check').fetchall():
                    raise RuntimeError('Migration copy has foreign key failures')
                for (name,) in source.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
                    quoted = '"' + name.replace('"', '""') + '"'
                    if source.execute(f'SELECT count(*) FROM {quoted}').fetchone() != destination.execute(f'SELECT count(*) FROM {quoted}').fetchone():
                        raise RuntimeError(f'Migration row count mismatch: {name}')
        temporary.replace(target)
    # Existing targets are upgraded in place, never replaced by the legacy store.
    from backend.market_store import MarketRecorder
    with MarketRecorder(target) as store:
        if store.connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or store.connection.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('Database validation failed after migration')
        # A crash after a raw receipt commit can leave a derived candle behind; recover its dirty minutes.
        from backend.candle_store import record_effect
        from types import SimpleNamespace
        missing = store.connection.execute('''SELECT o.ticker,o.source_time_epoch_ms,r.receipt_id,r.receipt_ms,r.is_exact_repeat
            FROM receipts r JOIN observations o USING(observation_id)
            LEFT JOIN ingestion_state s ON s.instrument_id=r.instrument_id
            WHERE r.receipt_id>COALESCE(s.last_receipt_id,0) ORDER BY r.receipt_id''').fetchall()
        for row in missing:
            record_effect(store.connection,row[0],SimpleNamespace(receipt_id=row[2],is_exact_repeat=bool(row[4])),row[1],row[3])
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', type=Path)
    parser.add_argument('--legacy', type=Path)
    args = parser.parse_args()
    print(prepare_database(args.database, args.legacy))
