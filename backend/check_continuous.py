"""TEST DATA: migration, backend ownership, session boundaries, and on-disk scale."""
import asyncio
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import statistics
import tempfile
import time
from unittest.mock import patch

from backend.database import prepare_database, DatabaseOwner, LEGACY_DATABASE
from backend.market_store import MarketRecorder
from backend.live_candles import CandleHub, CandleClient
from backend.recorded_history import recorded_history
from backend.write_coordinator import WriteCoordinator
from backend.candle_store import instrument, epoch


async def checks():
    root = Path(__file__).parent/'data'/'smoke-runs'
    root.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as folder:
        folder = Path(folder)
        source = folder/'legacy.sqlite3'
        with MarketRecorder(source) as store:
            store.connection.execute('CREATE TABLE preserved_student_work(id INTEGER PRIMARY KEY,value TEXT)')
            store.connection.execute("INSERT INTO preserved_student_work VALUES (7,'keep me')")
            store.connection.commit()
        target = folder/'market.db'
        prepare_database(target,source)
        prepare_database(target,source)
        with closing(sqlite3.connect(target)) as c:
            assert c.execute('SELECT * FROM preserved_student_work').fetchall()==[(7,'keep me')]
            assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            assert c.execute('PRAGMA foreign_key_check').fetchall()==[]
        owner = DatabaseOwner(target)
        try:
            try:
                DatabaseOwner(target)
                raise AssertionError('Duplicate process owner accepted')
            except RuntimeError:
                pass
        finally:
            owner.close()
        bad = folder/'conflict.db'
        with closing(sqlite3.connect(bad)) as c:
            c.execute('CREATE TABLE unrelated(x)')
        try:
            prepare_database(bad,source)
            raise AssertionError('Conflicting destination accepted')
        except RuntimeError:
            pass
        # Rebuild an interrupted migration copy while retaining its original source.
        interrupted = folder/'resume.db'
        Path(str(interrupted)+'.migration').write_text('partial TEST DATA')
        prepare_database(interrupted,source)
        db = folder/'feed.db'
        hub = CandleHub(db)
        writer = WriteCoordinator()
        first = asyncio.Event()
        async def feed(symbol,on_message,on_connected):
            await on_connected()
            await on_message(dict(id=symbol,time=epoch('2026-11-13T20:59:05Z'),price=100,
                day_volume=1000,test_data=True,test_data_label='TEST DATA — continuous lifecycle'))
            first.set()
            await asyncio.Event().wait()
        with patch('backend.live_candles.market_status',return_value={'status':'open','label':'Market open'}), patch('backend.live_candles.listen_for_updates',feed):
            await hub.start(writer)
            await asyncio.wait_for(first.wait(),5)
            assert not hub.clients
            hub.clients[99] = CandleClient(None,'AAPL','1m')
            await hub.remove_client(99)
            assert not hub.tasks['AAPL'].done()
            await hub.close()
        for stamp,price in [('2026-11-16T14:30:05Z',101),('2026-11-16T14:30:20Z',103)]:
            now = datetime.fromisoformat(stamp.replace('Z','+00:00'))
            with MarketRecorder(db) as store:
                message = dict(id='AAPL',time=epoch(stamp),price=price,day_volume=1004,test_data=True)
                store.record_message(message,now)
                store.record_message(message,now)
        history = recorded_history(db,'AAPL','1m')
        assert [c['timestamp'] for c in history['candles']]==['2026-11-13T20:59:00Z','2026-11-16T14:30:00Z']
        assert history['candles'][-1]['close']==103 and history['candles'][-1]['volume'] is None
        with MarketRecorder(db) as store:
            assert store.connection.execute('SELECT count(*) FROM observations').fetchone()[0]==3
            assert store.connection.execute('SELECT count(*) FROM receipts').fetchone()[0]==5
        await writer.close()
        # Disk-backed million-minute prototype uses the actual production candle schema/read function.
        scale = folder/'scale.db'
        with MarketRecorder(scale) as store:
            c=store.connection
            iid=instrument(c,'AAPL')
            instrument(c,'MSFT')
            begin=epoch('2020-01-01T00:00:00Z')//1000
            c.executemany('INSERT INTO candles_1m VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                ((iid,begin+i*60,100,103,99,102,1000,1,'TEST DATA','2026-11-13',1,0) for i in range(1000000)))
            c.executemany('''INSERT INTO observations(ticker,source_time_epoch_ms,source_time_units,price,
                raw_payload_json,payload_hash,relationship) VALUES ('AAPL',?,'milliseconds',100,?,?,'new')''',
                ((begin*1000+i*10,'{"test_data":true,"test_data_label":"TEST DATA — scale audit"}',str(i)) for i in range(50000)))
            c.execute('''INSERT INTO receipts(observation_id,backend_receipt_time_utc,is_exact_repeat)
                SELECT observation_id,'2020-01-01T00:00:01Z',0 FROM observations''')
            c.executemany('''INSERT INTO candle_revisions(instrument_id,minute_start,open,high,low,close,volume,complete,source,session,known_at_ms)
                VALUES (?, ?,100,103,99,102,1000,1,'TEST DATA','2026-11-13',?)''',
                ((iid,begin+(i//5)*60,begin*1000+i) for i in range(50000)))
            c.commit()
            plan=[tuple(r) for r in c.execute('EXPLAIN QUERY PLAN SELECT * FROM candles_1m WHERE instrument_id=? AND minute_start<? ORDER BY minute_start DESC LIMIT 2000',(iid,2**62))]
            assert any('PRIMARY KEY' in row[-1] for row in plan)
        reads=[]
        for _ in range(25):
            started=time.perf_counter()
            page=recorded_history(scale,'AAPL','1m')
            reads.append((time.perf_counter()-started)*1000)
            assert len(page['candles'])==2000 and page['next_before']
        earlier=recorded_history(scale,'AAPL','1m',before=page['next_before'])
        assert earlier['candles'][-1]['timestamp']<page['candles'][0]['timestamp']
        assert recorded_history(scale,'MSFT','1m')['candles']==[]
        latencies=[]
        stress=CandleHub(scale)
        stress.writer=WriteCoordinator()
        async def send(i):
            started=time.perf_counter()
            now=datetime(2026,11,13,20,58,tzinfo=timezone.utc)
            message=dict(id='AAPL',time=int(now.timestamp()*1000)+i,price=100+i/1000,
                         day_volume=1000+i,test_data=True)
            await stress.writer.run(lambda:stress.publish_observation('AAPL',message,now,'TEST DATA — 100 observations/s'))
            latencies.append((time.perf_counter()-started)*1000)
        tasks=[]
        for i in range(200):
            tasks.append(asyncio.create_task(send(i)))
            await asyncio.sleep(.01)
        await asyncio.gather(*tasks)
        await stress.writer.close()
        await stress.close()
        p95=sorted(reads)[23]
        assert p95<=250,(p95,'history read target')
        assert sorted(latencies)[189]<=1000,'writer latency target'
        with closing(sqlite3.connect(scale)) as c:
            checkpoint=c.execute('PRAGMA wal_checkpoint(PASSIVE)').fetchone()
            assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        print(json.dumps(dict(label='TEST DATA — continuous migration and scale',checks='PASS',
            verified=['fresh/idempotent migration','preserved unrelated records','owner lock','conflict refusal',
                      'interrupted copy recovery','zero-browser recording','last tab does not stop feed',
                      'Friday/Monday adjacency','repeat audit','million candles + 50000 quotes/receipts/revisions','pagination','second symbol','200 writes at 100/s'],
            query_plan=plan,history_median_ms=statistics.median(reads),history_p95_ms=p95,
            writer_p95_ms=sorted(latencies)[189],file_bytes=scale.stat().st_size,checkpoint=checkpoint),indent=2))


if __name__=='__main__':
    asyncio.run(checks())
