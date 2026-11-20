"""Offline causality, execution, migration, persistence and API isolation checks."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.backtesting import digest, run_backtest, settings, text
from backend.backtest_store import BacktestStore, load_dataset
from backend.database import prepare_database
from backend.market_store import MarketRecorder
from backend.paper_trading import PaperAccount, execute_paper_action
from backend.yahoo_history import save_bars

START = datetime(2026,11,9,14,30,tzinfo=timezone.utc)


def fixture(mode='historical_bars'):
    config = settings(dict(symbol='AAPL',timeframe='1m',start=text(START),
        end=text(START+timedelta(minutes=7)),fast_window=1,slow_window=2,quantity=4,
        starting_cash=1000,data_mode=mode,frozen_at=text(START+timedelta(days=1))))
    bars = []
    for i,(close,opening) in enumerate(zip([10,12,9,13,8,8],[10,10,10,10,100,110])):
        beginning=START+timedelta(minutes=i)
        end=beginning+timedelta(minutes=1)
        bars.append(dict(timestamp=text(beginning),end_time=text(end),
            available_at=text(end+timedelta(seconds=5)) if mode=='recorded' else text(end),
            open=opening,high=max(opening,close)+1,low=min(opening,close)-1,close=close,
            volume=100,complete=True,coverage_complete=True,source='TEST DATA'))
    dataset=dict(version=1,symbol='AAPL',timeframe='1m',data_mode=mode,frozen_at=config['frozen_at'],
                 bars=bars,prices=[],provenance=dict(source='TEST DATA constructed backtest'))
    if mode=='recorded':
        for i,price in ((3,100),(4,110)):
            when=START+timedelta(minutes=i+1,seconds=5)
            dataset['prices'] += [dict(event_id=f'same-{i}',price=price,available_at=text(when)),
                                  dict(event_id=f'next-{i}',price=price,available_at=text(when+timedelta(seconds=1)))]
    return config,dataset


class EngineChecks(unittest.TestCase):
    def test_known_trades_next_open_and_no_liquidation(self):
        config,dataset=fixture()
        result=run_backtest(config,dataset)
        self.assertEqual([row['action'] for row in result['orders']],['buy','close'])
        self.assertEqual([row['fill']['price'] for row in result['orders']],[100,110])
        self.assertEqual(result['summary']['equity'],1040)
        self.assertEqual(result['summary']['realized'],40)
        self.assertEqual(result['summary']['shares'],0)
        self.assertEqual(result['orders'][0]['submitted_at'],text(START+timedelta(minutes=4)))
        self.assertEqual(result['orders'][0]['fill']['execution_time'],text(START+timedelta(minutes=4)))
        shortened=deepcopy(dataset)
        shortened['bars']=shortened['bars'][:4]
        pending=run_backtest(config,shortened)
        self.assertEqual((pending['summary']['fills'],pending['summary']['pending'],pending['summary']['cash']),(0,1,1000))
        partial=deepcopy(dataset)
        partial['bars'][4].update(complete=False,coverage_complete=False)
        still_fills=run_backtest(config,partial)
        self.assertEqual(still_fills['orders'][0]['fill']['price'],100,'the next open cannot depend on that bar becoming complete later')

    def test_warmup_and_future_changes_do_not_change_earlier_decisions(self):
        config,dataset=fixture()
        baseline=run_backtest(config,dataset)
        changed=deepcopy(dataset)
        changed['bars'][5].update(close=999,high=1000)
        future=run_backtest(config,changed)
        self.assertEqual(baseline['decisions'][:5],future['decisions'][:5])
        self.assertEqual(baseline['equity'][:3], [{**row,'run_id':baseline['run_id']} for row in future['equity'][:3]])
        warm=dict(config,start=dataset['bars'][3]['timestamp'])
        result=run_backtest(warm,dataset)
        self.assertEqual(len(result['decisions']),3)
        self.assertEqual(result['decisions'][0]['signal'],'upward')
        self.assertTrue(all(row['bar_time']>=warm['start'] for row in result['decisions']))

    def test_recorded_receipt_cannot_fill_its_own_signal_and_late_revision_is_not_retroactive(self):
        config,dataset=fixture('recorded')
        result=run_backtest(config,dataset)
        self.assertEqual([row['fill']['event_id'] for row in result['orders']],['next-3','next-4'])
        self.assertEqual(result['summary']['equity'],1040)
        revised=deepcopy(dataset)
        revision={**revised['bars'][4], 'close':20,'available_at':text(START+timedelta(minutes=5,seconds=20))}
        revised['bars'].append(revision)
        latest=run_backtest(config,revised)
        self.assertEqual(result['decisions'][:5],latest['decisions'][:5])
        self.assertEqual(result['decisions'][-1]['signal'],'none')
        self.assertEqual(latest['decisions'][-1]['signal'],'downward')
        self.assertEqual(len(latest['decisions']),len(result['decisions']))

    def test_same_time_backfill_makes_only_latest_decision_and_partial_data_cannot_signal(self):
        config,dataset=fixture('recorded')
        for row in dataset['bars']:
            row['available_at']=text(START+timedelta(minutes=6,seconds=20))
        result=run_backtest(config,dataset)
        self.assertEqual(len(result['decisions']),1)
        self.assertEqual(result['decisions'][0]['bar_time'],dataset['bars'][-1]['timestamp'])
        config,dataset=fixture()
        dataset['bars'][3]['coverage_complete']=False
        partial=run_backtest(config,dataset)
        self.assertFalse(partial['decisions'][3]['available'])
        self.assertEqual(partial['summary']['fills'],0)
        dataset['bars'][3].update(coverage_complete=True,complete=False)
        self.assertEqual(run_backtest(config,dataset)['summary']['fills'],0)

    def test_loader_preserves_actual_availability_and_ignores_later_revisions(self):
        config,dataset=fixture('recorded')
        with tempfile.TemporaryDirectory(prefix='recorded-backtest-') as directory:
            path=Path(directory)/'fixture.db'
            with MarketRecorder(path) as recorder:
                for price in dataset['prices']:
                    when=datetime.fromisoformat(price['available_at'].replace('Z','+00:00'))
                    recorder.record_message(dict(id='AAPL',time=int(when.timestamp()*1000),price=price['price'],test_data=True),when)
                iid=recorder.connection.execute("SELECT instrument_id FROM instruments WHERE symbol='AAPL'").fetchone()[0]
                for bar in dataset['bars']:
                    timestamp=int(datetime.fromisoformat(bar['timestamp'].replace('Z','+00:00')).timestamp())
                    known=int(datetime.fromisoformat(bar['available_at'].replace('Z','+00:00')).timestamp()*1000)
                    recorder.connection.execute('''INSERT INTO candle_revisions(instrument_id,minute_start,open,high,low,close,volume,complete,source,session,known_at_ms)
                        VALUES (?,?,?,?,?,?,?,1,'TEST DATA recorded bar','2026-11-09',?)''',
                        (iid,timestamp,bar['open'],bar['high'],bar['low'],bar['close'],bar['volume'],known))
                recorder.connection.commit()
                resolved,frozen=load_dataset(path,config)
                result=run_backtest(resolved,frozen)
                self.assertEqual([row['fill']['price'] for row in result['orders']],[100,110])
                self.assertEqual([row['fill']['event_id'] for row in result['orders']],['receipt:2','receipt:4'])
                recorder.connection.execute('''INSERT INTO candle_revisions(instrument_id,minute_start,open,high,low,close,volume,complete,source,session,known_at_ms)
                    VALUES (?,?,10,1000,1,999,100,1,'TEST DATA late revision','2026-11-09',?)''',
                    (iid,int(START.timestamp()),int((START+timedelta(hours=2)).timestamp()*1000)))
                recorder.connection.commit()
                _,later=load_dataset(path,config)
                self.assertEqual(digest(frozen),digest(later),'a revision only available after the requested end is excluded')

    def test_bounds_invalid_data_and_no_recorded_knowledge_from_later_download(self):
        config,dataset=fixture()
        for change in (dict(fast_window=2),dict(quantity=0),dict(timeframe='other'),dict(start=config['end'])):
            with self.assertRaises(ValueError):
                settings(dict(config,**change))
        bad=deepcopy(dataset)
        bad['bars'][0]['high']=1
        with self.assertRaises(ValueError):
            run_backtest(config,bad)
        with tempfile.TemporaryDirectory(prefix='late-download-') as directory:
            path=Path(directory)/'fixture.db'
            with MarketRecorder(path): pass
            with self.assertRaisesRegex(ValueError,'future'):
                load_dataset(path,dict(config,frozen_at=text(datetime.now(timezone.utc)+timedelta(days=1))))
            save_bars(path,'AAPL',[{key:bar[key] for key in ('timestamp','open','high','low','close','volume')} for bar in dataset['bars']],START+timedelta(days=1))
            recorded=dict(config,data_mode='recorded')
            resolved,frozen=load_dataset(path,recorded)
            self.assertEqual(frozen['bars'],[],'a next-day download was not known during the requested session')
            with self.assertRaisesRegex(ValueError,'No stored bars'):
                run_backtest(resolved,frozen)

    def test_persistence_hash_rerun_and_newer_schema_refusal(self):
        config,dataset=fixture()
        result=run_backtest(config,dataset)
        repeat=run_backtest(config,dataset)
        self.assertEqual(result['result_hash'],repeat['result_hash'])
        self.assertNotEqual(result['run_id'],repeat['run_id'])
        with tempfile.TemporaryDirectory(prefix='backtest-store-') as directory:
            path=Path(directory)/'fixture.db'
            with MarketRecorder(path), PaperAccount(path,1234) as paper:
                execute_paper_action(paper,request_id='preserved',symbol='AAPL',action='buy',quantity=1,submitted_at=START)
                before=paper.snapshot('AAPL')
                # Construct an older schema in this disposable fixture, never production.
                for table in ('backtest_equity','backtest_decisions','backtest_orders','backtest_runs','backtest_datasets'):
                    paper.connection.execute(f'DROP TABLE {table}')
                paper.connection.execute('DELETE FROM schema_migrations WHERE version=5')
                paper.connection.commit()
                prepare_database(path)
                self.assertEqual(paper.snapshot('AAPL'),before)
                store=BacktestStore(path)
                store.save('test',digest(config),dataset,result)
                self.assertEqual(store.existing('test',digest(config))['run_id'],result['run_id'])
                store.close()
                store=BacktestStore(path)
                self.assertEqual(store.get(result['run_id']),result)
                frozen=store.dataset(result['run_id'])
                self.assertEqual(run_backtest(config,frozen)['result_hash'],result['result_hash'])
                self.assertEqual(paper.snapshot('AAPL'),before)
                self.assertEqual(paper.connection.execute('PRAGMA foreign_key_check').fetchall(),[])
                store.close()
                paper.connection.execute("INSERT INTO schema_migrations VALUES (6,'TEST DATA')")
                paper.connection.commit()
                with self.assertRaises(RuntimeError):
                    prepare_database(path)


class ApiChecks(unittest.TestCase):
    def test_create_list_retrieve_rerun_invalid_empty_and_account_isolation(self):
        from fastapi.testclient import TestClient
        with tempfile.TemporaryDirectory(prefix='backtest-api-') as directory:
            path=Path(directory)/'fixture.db'
            config,dataset=fixture()
            with MarketRecorder(path):
                pass
            bars=[{key:row[key] for key in ('timestamp','open','high','low','close','volume')} for row in dataset['bars']]
            save_bars(path,'AAPL',bars,START+timedelta(days=1))
            with patch.dict(os.environ,MARKET_DATABASE=str(path),MARKET_LIVE_FEED='0',MARKET_CANDLE_FILE='',PAPER_STARTING_CASH='1000'):
                from backend import main
                with TestClient(main.app) as client:
                    before=client.get('/api/paper-account').json()
                    response=client.post('/api/backtests',json=dict(config,request_id='create-test'))
                    self.assertEqual(response.status_code,201,response.text)
                    result=response.json()
                    self.assertEqual(result['summary']['equity'],1040)
                    self.assertEqual(client.post('/api/backtests',json=dict(config,request_id='create-test')).json()['run_id'],result['run_id'])
                    conflict=client.post('/api/backtests',json=dict(config,request_id='create-test',quantity=1))
                    self.assertEqual(conflict.status_code,409)
                    self.assertEqual(client.get('/api/backtests').json()['runs'][0]['run_id'],result['run_id'])
                    self.assertEqual(client.get(f'/api/backtests/{result["run_id"]}').json(),result)
                    saved=client.get(f'/api/backtests/{result["run_id"]}/dataset').json()
                    self.assertEqual(digest(saved),result['dataset_hash'])
                    rerun=client.post(f'/api/backtests/{result["run_id"]}/rerun',json=dict(request_id='rerun-test'))
                    self.assertEqual(rerun.status_code,201,rerun.text)
                    self.assertEqual(rerun.json()['result_hash'],result['result_hash'])
                    self.assertNotEqual(rerun.json()['run_id'],result['run_id'])
                    self.assertEqual(client.post('/api/backtests',json=dict(config,request_id='bad',fast_window=2)).status_code,422)
                    self.assertEqual(client.post('/api/backtests',json=dict(config,request_id='empty',symbol='EMPTY')).status_code,422)
                    self.assertEqual(client.get('/api/backtests/missing').status_code,404)
                    self.assertEqual(client.get('/api/paper-account').json(),before)
                    self.assertEqual(main.paper_account.connection.execute('SELECT COUNT(*) FROM paper_fills').fetchone()[0],0)


if __name__=='__main__':
    unittest.main(verbosity=2)
