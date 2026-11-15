"""Seed a separate TEST DATA Friday-close database for the browser SmokeTest."""
import argparse
from datetime import datetime, timezone
from backend.market_store import MarketRecorder
from backend.candle_store import epoch
from backend.candle_store import session_bounds, stamp
from backend.yahoo_history import save_bars


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--database',required=True)
    args=parser.parse_args()
    # A realistic five-session payload catches proxy/body failures hidden by two-row fixtures.
    candles=[]
    for day in range(9,14):
        opening,closing=session_bounds(f'2026-11-{day:02d}')
        candles.extend(dict(timestamp=stamp(t),open=100,high=100,low=100,close=100,volume=100)
                       for t in range(opening,closing,60))
    save_bars(args.database,'AAPL',candles,datetime(2026,11,13,21,0,1,tzinfo=timezone.utc))
    with MarketRecorder(args.database) as store:
        store.record_message(dict(id='AAPL',time=epoch('2026-11-13T20:59:50Z'),price=100,
            day_volume=1000,test_data=True,test_data_label='TEST DATA — continuous browser fixture'),
            datetime(2026,11,13,21,0,1,tzinfo=timezone.utc))
