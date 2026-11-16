"""TEST DATA: company selection recovers cold history while the market is closed."""
import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
from threading import Event
from unittest.mock import patch
from backend.market_store import MarketRecorder
from backend.recorded_history import recorded_history
from backend.yahoo_history import save_bars


async def check():
    root=Path(__file__).parent/'data'/'smoke-runs'
    root.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as folder:
        os.environ.update(MARKET_DATABASE=str(Path(folder)/'market.db'),MARKET_LIVE_FEED='1',
                          MARKET_TEST_FEED='0',MARKET_MANUAL_TEST_FEED='0',MARKET_CANDLE_FILE='')
        from backend import main
        now=datetime(2026,11,13,21,1,tzinfo=timezone.utc)
        candle=dict(timestamp='2026-11-13T20:59:00Z',open=100,high=103,low=99,close=102,volume=25)
        calls=[]
        release=Event()
        def download(*args):
            calls.append(args)
            if not release.wait(5):
                raise AssertionError('selection waited for provider instead of returning immediately')
            return dict(status='ok',bar_count=1,message=None,candles=[candle],fetched=now,started=now)
        async def selection():
            return await main.history(symbol='AAPL',timeframe='1m',as_of=None,limit=2000,before=None,start=None,recent=True)
        try:
            with patch.object(main,'fetch_recent',download):
                a,b=await asyncio.wait_for(asyncio.gather(selection(),selection()),timeout=2)
                assert a['candles']==b['candles']==[], 'cold selections return promptly without waiting for Yahoo'
                release.set()
                await main.recent_history_tasks['AAPL']
                assert (await selection())['candles']==[candle]
                assert len(calls)==1,'concurrent company clicks share one download'
                assert a['market']['status']=='closed'
                assert (await selection())['candles']==[candle]
                assert len(calls)==1,'rapid clicks reuse recent attempt'
            main.recent_history_attempts.clear()
            failure=dict(status='unavailable',bar_count=0,message='TEST DATA — Yahoo unavailable',candles=[],fetched=now,started=now)
            with patch.object(main,'fetch_recent',return_value=failure):
                assert (await selection())['candles']==[candle],'saved candles remain visible during failure'
                await main.recent_history_tasks['AAPL']
                result=await selection()
                assert result['candles']==[candle] and result['history_fetch']['status']=='unavailable'
            blocked=asyncio.create_task(asyncio.sleep(10))
            try:
                with patch.object(main,'request_interval_history',return_value=blocked), patch.object(main,'request_daily_history',return_value=blocked), patch.object(main,'request_recent_history',return_value=blocked):
                    for interval in ('5m','1d'):
                        page=await asyncio.wait_for(main.history(symbol='AAPL',timeframe=interval,as_of=None,limit=500,before=None,start=None,recent=True),timeout=2)
                        assert page['candles'][0]['close']==102,'local minute aggregation appears while provider is blocked'
                        assert page['interval_download_pending'] if interval=='5m' else page['daily_download_pending']
            finally:
                blocked.cancel()
                await asyncio.gather(blocked,return_exceptions=True)

            # TEST DATA: commit a corrected bar between HTTP read and socket subscription.
            initial=recorded_history(main.DATABASE_PATH,'AAPL','1m',limit=500)
            save_bars(main.DATABASE_PATH,'AAPL',[{**candle,'close':104,'high':104,'volume':50}],datetime.now(timezone.utc))
            class Socket:
                def __init__(self,stream_id):
                    self.messages=[]
                    self.query_params=dict(stream_id=stream_id,since=str(initial['watermark']),
                        daily_since='0',interval_since='0',limit='500')
                async def accept(self): pass
                async def send_json(self,message): self.messages.append(message)
            hub=main.candle_hub
            hub.manual_test=True
            hub._now=lambda:datetime.now(timezone.utc)
            resumed=Socket(hub.stream_id)
            fresh=Socket('previous-backend-instance')
            a=await hub.add_client(resumed,'AAPL','1m')
            b=await hub.add_client(fresh,'AAPL','1m')
            for _ in range(30):
                if resumed.messages and fresh.messages: break
                await asyncio.sleep(.01)
            assert not any(m['type']=='history' for m in resumed.messages),'valid resume avoids duplicate full history'
            assert any(m['type']=='candle' and m['candle']['close']==104 and m['candle']['volume']==50 for m in resumed.messages),'intervening revision is delivered'
            assert any(m['type']=='history' and len(m['candles'])<=500 for m in fresh.messages),'new backend identity forces a safe bounded snapshot'
            await hub.remove_client(a)
            await hub.remove_client(b)
            print('PASS TEST DATA: nonblocking closed-market cold selection, coalesced download, retry throttle, cache on Yahoo failure; no orders')
            print('PASS TEST DATA: 5m/daily ignore blocked provider; revision catch-up bridges HTTP/socket gap; restart falls back to bounded snapshot')
        finally:
            release.set()
            await main.stop_candle_hub()


if __name__=='__main__':
    asyncio.run(check())
