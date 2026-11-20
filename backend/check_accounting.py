"""Known examples and isolated-vs-SQLite accounting parity; disposable stores only."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.accounting import FillRejected, Position, apply_fill, dollars_to_cents, quote_entry, value_position
from backend.market_store import MarketRecorder
from backend.paper_trading import PaperAccount, execute_paper_action
from backend.simulation_account import SimulationAccount


START = datetime(2026, 11, 9, 15, tzinfo=timezone.utc)


def at(seconds):
    return START + timedelta(seconds=seconds)


def amounts(row):
    return tuple(row[key] for key in ('cash', 'shares', 'realized', 'unrealized', 'total_pnl'))


class AccountingChecks(unittest.TestCase):
    def test_known_example_and_sqlite_parity(self):
        with tempfile.TemporaryDirectory(prefix='accounting-check-') as directory:
            path = Path(directory) / 'fixture.db'
            with MarketRecorder(path) as recorder, PaperAccount(path, 1000) as paper:
                sim = SimulationAccount(symbol='AAPL', starting_cash=1000)

                def submit(action, offset, quantity=None):
                    request = f'{action}-{offset}'
                    sim.submit(request_id=request, action=action, quantity=quantity, submitted_at=at(offset))
                    execute_paper_action(paper, request_id=request, symbol='AAPL', action=action,
                                         quantity=quantity, submitted_at=at(offset))

                def event(offset, price, mark=False):
                    stored = recorder.record_message(dict(id='AAPL', time=int(at(offset).timestamp()*1000),
                                                          price=price, test_data=True), at(offset))
                    if mark:
                        sim.mark(event_id=str(offset), price=price, available_at=at(offset))
                        paper.record_completed_candle_valuation(event_key=str(offset), symbol='AAPL', price=price,
                            event_time=at(offset), source='TEST DATA', observation_id=stored.observation_id, receipt_id=stored.receipt_id)
                    else:
                        sim.observe(event_id=str(offset), price=price, available_at=at(offset))
                        paper.process_market_observation(symbol='AAPL', price=price, observation_id=stored.observation_id,
                            receipt_id=stored.receipt_id, arrival_time=at(offset), source='TEST DATA')
                    saved = paper.snapshot('AAPL')
                    self.assertEqual(sim.snapshot()['cash'], saved['cash'])
                    self.assertEqual(sim.snapshot()['shares'], saved['shares'])
                    self.assertEqual(sim.snapshot()['average_cost'], saved['average_cost'])
                    self.assertEqual(amounts(sim.snapshot()), amounts(saved['pnl_history'][-1]))

                submit('buy', 0, 4)
                self.assertEqual(sim.snapshot()['cash'], 1000)
                event(1, 100)
                event(2, 110, mark=True)
                # Repeated valuation is idempotent in both adapters.
                sim.mark(event_id='2', price=110, available_at=at(2))
                submit('sell', 3, 1)
                event(4, 110)
                event(5, 95, mark=True)
                submit('close', 6)
                event(7, 105)
                expected = [(600,4,0,0,0),(600,4,0,40,40),(710,3,10,30,40),
                            (710,3,10,-15,-5),(1025,0,25,0,25)]
                self.assertEqual([amounts(row) for row in sim.snapshot()['pnl_history']], expected)
                self.assertEqual([amounts(row) for row in paper.snapshot('AAPL')['pnl_history']], expected)
                self.assertEqual(paper.connection.execute('SELECT COUNT(*) FROM paper_fills').fetchone()[0], 3)
                self.assertEqual(paper.connection.execute('SELECT COUNT(*) FROM paper_pnl_history').fetchone()[0], 5)
            with PaperAccount(path, 1) as reopened:
                self.assertEqual([amounts(row) for row in reopened.snapshot('AAPL')['pnl_history']], expected)

    def test_weighted_average_and_cent_residual(self):
        cash, position = 100000, Position()
        for quantity, price in ((1,10000),(2,10001)):
            filled = apply_fill(cash, position, 'buy', quantity, price)
            cash, position = filled.cash_cents, filled.position
        self.assertEqual(position.cost_basis_cents, 30002)
        filled = apply_fill(cash, position, 'sell', 1, 11000)
        self.assertEqual(filled.position, Position(2,20001,999))
        self.assertEqual(value_position(filled.position,9500)['unrealized_cents'], -1001)
        closed = apply_fill(filled.cash_cents, filled.position, 'sell', 2, 9000)
        self.assertEqual(closed.position, Position(0,0,-1002))
        self.assertEqual(closed.cash_cents, 98998)
        self.assertEqual(dollars_to_cents('1.005'),101)
        self.assertEqual(dollars_to_cents('1.004'),100)
        self.assertEqual(quote_entry('1.005',2),dict(price_cents=101,estimated_cost_cents=202))

    def test_fill_rejections_are_pure_and_fifo_rechecks_cash(self):
        position = Position(1,10000,0)
        with self.assertRaises(FillRejected):
            apply_fill(5000,position,'buy',1,10000)
        with self.assertRaises(FillRejected):
            apply_fill(5000,position,'sell',2,10000)
        self.assertEqual(position,Position(1,10000,0))
        sim = SimulationAccount(symbol='AAPL',starting_cash=100)
        for request in ('first','second'):
            sim.submit(request_id=request,action='buy',quantity=1,submitted_at=at(0))
        result = sim.observe(event_id='next',price=60,available_at=at(1))
        self.assertEqual([row['status'] for row in result],['filled','rejected'])
        self.assertEqual((sim.snapshot()['cash'],sim.snapshot()['shares']),(40,1))

    def test_pending_idempotency_unknown_mark_and_immutable_history(self):
        sim = SimulationAccount(symbol='AAPL',starting_cash=1000)
        sim.observe(event_id='already-known',price=50,available_at=at(0))
        pending = sim.submit(request_id='buy',action='buy',quantity=2,submitted_at=at(1))
        self.assertEqual(pending['status'],'pending')
        self.assertEqual(sim.observe(event_id='already-known',price=50,available_at=at(0)),[])
        self.assertEqual(sim.snapshot()['shares'],0)
        sim.observe(event_id='later-receipt-same-price',price=50,available_at=at(2))
        self.assertEqual(sim.submit(request_id='buy',action='buy',quantity=2,submitted_at=at(1))['status'],'filled')
        self.assertEqual(sim.observe(event_id='later-receipt-same-price',price=50,available_at=at(2)),[])
        with self.assertRaises(ValueError):
            sim.observe(event_id='later-receipt-same-price',price=60,available_at=at(2))
        missing = sim.mark(event_id='missing',price=None,available_at=at(3))
        self.assertFalse(missing['valuation_available'])
        self.assertIsNone(missing['unrealized'])
        self.assertIsNone(missing['equity'])
        self.assertEqual(missing['cash'],900)
        prior = sim.snapshot()['pnl_history']
        prior[0]['cash'] = -999
        sim.mark(event_id='recovery',price=55,available_at=at(4))
        self.assertEqual(sim.snapshot()['unrealized'],10)
        self.assertEqual(sim.snapshot()['pnl_history'][0]['cash'],900)
        self.assertIsNone(sim.snapshot()['pnl_history'][1]['unrealized'])

    def test_bar_adapter_only_uses_next_open_and_never_the_decision_close(self):
        sim = SimulationAccount(symbol='AAPL',starting_cash=1000,execution='bar_open')
        sim.bar_open(event_id='signal-bar',open_price=90,bar_start=at(0))
        sim.mark(event_id='signal-close',price=100,available_at=at(60))
        sim.submit(request_id='enter',action='buy',quantity=2,submitted_at=at(60))
        self.assertEqual(sim.snapshot()['shares'],0)
        sim.mark(event_id='later-close-valuation',price=200,available_at=at(60))
        self.assertEqual(sim.snapshot()['shares'],0,'a valuation cannot fill the pending order')
        with self.assertRaises(ValueError):
            sim.bar_open(event_id='old-bar',open_price=90,bar_start=at(0))
        sim.bar_open(event_id='next-bar',open_price=110,bar_start=at(60))
        self.assertEqual((sim.snapshot()['cash'],sim.snapshot()['shares']),(780,2))
        self.assertEqual(sim.snapshot()['orders'][0]['fill']['price'],110)
        with self.assertRaises(ValueError):
            sim.observe(event_id='wrong-adapter',price=100,available_at=at(61))
        with self.assertRaises(ValueError):
            sim.submit(request_id='past',action='close',submitted_at=at(59))

    def test_independent_runs_cannot_reach_sqlite_or_each_other(self):
        with tempfile.TemporaryDirectory(prefix='account-isolation-') as directory:
            database = Path(directory)/'unrelated-paper.db'
            with MarketRecorder(database), PaperAccount(database,1000) as paper:
                before = paper.snapshot('AAPL')
                with patch('sqlite3.connect',side_effect=AssertionError('simulation tried to open a database')):
                    first = SimulationAccount(symbol='AAPL',starting_cash=1000)
                    second = SimulationAccount(symbol='AAPL',starting_cash=500)
                    first.submit(request_id='same-request',action='buy',quantity=2,submitted_at=at(0))
                    first.observe(event_id='same-event',price=100,available_at=at(1))
                    second.submit(request_id='same-request',action='buy',quantity=1,submitted_at=at(0))
                    second.observe(event_id='same-event',price=50,available_at=at(1))
                    self.assertNotEqual(first.run_id,second.run_id)
                    self.assertEqual((first.snapshot()['cash'],second.snapshot()['cash']),(800,450))
                    self.assertEqual((first.snapshot()['shares'],second.snapshot()['shares']),(2,1))
                self.assertEqual(paper.snapshot('AAPL'),before)
                self.assertEqual(paper.connection.execute('SELECT COUNT(*) FROM paper_orders').fetchone()[0],0)

    def test_unknown_legacy_basis_and_invalid_quantities(self):
        unknown = Position(3,None,None)
        self.assertFalse(value_position(unknown,10000)['valuation_available'])
        sold = apply_fill(0,unknown,'sell',3,10000)
        self.assertIsNone(sold.position.realized_pnl_cents)
        self.assertEqual(sold.position.cost_basis_cents,0)
        self.assertIsNone(value_position(sold.position,10000)['total_pnl_cents'])
        sim = SimulationAccount(symbol='AAPL',starting_cash=1000)
        for quantity in (0,-1,1.5,True):
            self.assertEqual(sim.submit(request_id=str(quantity),action='buy',quantity=quantity,submitted_at=at(0))['status'],'rejected')
        for action in ('hold','wait'):
            self.assertIsNone(sim.submit(request_id=action,action=action,submitted_at=at(0))['order'])
        self.assertEqual(len(sim.snapshot()['orders']),4)
        with self.assertRaises(ValueError):
            sim.mark(event_id='naive',price=10,available_at=datetime(2026,11,9))

    def test_pending_sales_recheck_shares_and_realized_pnl_survives_new_entry(self):
        sim = SimulationAccount(symbol='AAPL',starting_cash=1000)
        sim.submit(request_id='buy',action='buy',quantity=2,submitted_at=at(0))
        sim.observe(event_id='entry',price=100,available_at=at(1))
        sim.submit(request_id='sell',action='sell',quantity=2,submitted_at=at(2))
        sim.submit(request_id='close',action='close',submitted_at=at(2))
        result = sim.observe(event_id='exit',price=110,available_at=at(3))
        self.assertEqual([row['status'] for row in result],['filled','rejected'])
        self.assertEqual((sim.snapshot()['cash'],sim.snapshot()['shares'],sim.snapshot()['realized']),(1020,0,20))
        sim.submit(request_id='buy-again',action='buy',quantity=1,submitted_at=at(4))
        sim.observe(event_id='re-entry',price=50,available_at=at(5))
        sim.mark(event_id='revalue',price=60,available_at=at(6))
        snapshot = sim.snapshot()
        self.assertEqual((snapshot['realized'],snapshot['unrealized'],snapshot['total_pnl']),(20,10,30))
        self.assertEqual(snapshot['equity']-snapshot['initial_cash'],snapshot['total_pnl'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
