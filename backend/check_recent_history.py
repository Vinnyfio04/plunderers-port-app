"""TEST DATA: company selection recovers cold history while the market is closed."""
import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
from unittest.mock import patch


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
        def download(*args):
            calls.append(args)
            return dict(status='ok',bar_count=1,message=None,candles=[candle],fetched=now,started=now)
        async def selection():
            return await main.history(symbol='AAPL',timeframe='1m',as_of=None,limit=2000,before=None,start=None,recent=True)
        try:
            with patch.object(main,'fetch_recent',download):
                a,b=await asyncio.gather(selection(),selection())
                assert a['candles']==b['candles']==[candle]
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
            print('PASS TEST DATA: closed-market cold selection, coalesced download, retry throttle, cache on Yahoo failure; no orders')
        finally:
            await main.stop_candle_hub()


if __name__=='__main__':
    asyncio.run(check())
