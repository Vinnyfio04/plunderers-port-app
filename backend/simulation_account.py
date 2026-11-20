"""Run-local accounting adapter, not a strategy loop or a persistent backtester.

There is deliberately no database/path argument and no import of the live account.
Each instance owns its cash, immutable position, orders, events and valuation log.
"""
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from backend.accounting import FillRejected, Position, apply_fill, cents_to_dollars, dollars_to_cents, value_position


def _time(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError('Simulation event times must be timezone-aware datetimes.')
    return value.astimezone(timezone.utc)


def _text(value):
    return value.isoformat().replace('+00:00', 'Z')


class SimulationAccount:
    def __init__(self, *, symbol, starting_cash='10000', execution='observation'):
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError('A simulation symbol is required.')
        if execution not in ('observation', 'bar_open'):
            raise ValueError('Execution must be observation or bar_open.')
        self.run_id = f'sim_{uuid4().hex}'
        self.symbol = symbol.strip().upper()
        self.execution = execution
        self._initial = self._cash = dollars_to_cents(starting_cash)
        self._position = Position()
        self._orders = []
        self._pending = []
        self._requests = {}
        self._events = {}
        self._marks = {}
        self._history = []
        self._sequence = 0
        self._clock = None
        self._price = None

    def _ordered(self, when):
        timestamp = _time(when)
        if self._clock is not None and timestamp < self._clock:
            raise ValueError('Simulation events must arrive in nondecreasing availability order.')
        return timestamp

    def submit(self, *, request_id, action, submitted_at, quantity=None):
        if not isinstance(request_id, str) or not request_id.strip() or len(request_id.strip()) > 128:
            raise ValueError('A request ID of 1–128 characters is required.')
        request_id = request_id.strip()
        if action not in ('buy', 'sell', 'close', 'hold', 'wait'):
            raise ValueError('Action must be buy, sell, close, hold or wait.')
        if request_id in self._requests:
            return deepcopy(self._requests[request_id])
        timestamp = self._ordered(submitted_at)
        self._clock = timestamp
        if action in ('hold', 'wait'):
            return dict(status='no_order', order=None)
        rejection = None
        if action == 'close':
            quantity = self._position.quantity
            if quantity == 0:
                rejection = 'Cannot close an empty position.'
        elif isinstance(quantity, bool) or not isinstance(quantity, int):
            quantity = None
            rejection = 'Quantity must be a whole number of shares.'
        elif quantity < 1:
            rejection = 'Quantity must be greater than zero.'
        elif action == 'sell' and quantity > self._position.quantity:
            rejection = f'Cannot sell {quantity} shares; position holds {self._position.quantity}.'
        order = dict(run_id=self.run_id, order_id=len(self._orders) + 1, request_id=request_id,
                     symbol=self.symbol, action=action, side='buy' if action == 'buy' else 'sell',
                     quantity=quantity, submitted_at=_text(timestamp), submission_sequence=self._sequence,
                     status='rejected' if rejection else 'pending', rejection_reason=rejection, fill=None)
        self._orders.append(order)
        if order['status'] == 'pending':
            self._pending.append(order)
        self._requests[request_id] = order
        return deepcopy(order)

    def observe(self, *, event_id, price, available_at):
        if self.execution != 'observation':
            raise ValueError('This simulation accepts bar opens, not observation events.')
        return self._process(event_id, price, available_at, 'observation')

    def bar_open(self, *, event_id, open_price, bar_start):
        if self.execution != 'bar_open':
            raise ValueError('This simulation accepts observations, not historical bar opens.')
        # Only open/time are accepted: high/low/close cannot enter this fill adapter.
        return self._process(event_id, open_price, bar_start, 'bar_open')

    def _process(self, event_id, price, when, source):
        if not isinstance(event_id, str) or not event_id:
            raise ValueError('An immutable price event ID is required.')
        timestamp = _time(when)
        price_cents = dollars_to_cents(price)
        fingerprint = (_text(timestamp), price_cents, source)
        if event_id in self._events:
            if self._events[event_id] != fingerprint:
                raise ValueError('A repeated event ID cannot change its price, availability time or source.')
            return []
        self._ordered(timestamp)
        self._clock = timestamp
        self._events[event_id] = fingerprint
        self._sequence += 1
        self._price = price_cents
        results = []
        for order in self._pending:
            if order['status'] != 'pending' or order['submission_sequence'] >= self._sequence:
                continue
            try:
                filled = apply_fill(self._cash, self._position, order['side'], order['quantity'], price_cents)
            except FillRejected as error:
                order.update(status='rejected', rejection_reason=str(error))
                results.append(deepcopy(order))
                continue
            self._cash, self._position = filled.cash_cents, filled.position
            order.update(status='filled', fill=dict(event_id=event_id, sequence=self._sequence,
                         price=cents_to_dollars(price_cents), execution_time=_text(timestamp), source=source))
            self._record(timestamp, f'fill:{order["order_id"]}', source)
            results.append(deepcopy(order))
        self._pending = [order for order in self._pending if order['status'] == 'pending']
        return results

    def mark(self, *, event_id, price, available_at):
        """Value holdings without filling orders; None means the price is unavailable."""
        if not isinstance(event_id, str) or not event_id:
            raise ValueError('An immutable valuation ID is required.')
        timestamp = _time(available_at)
        price_cents = dollars_to_cents(price) if price is not None else None
        fingerprint = (_text(timestamp), price_cents)
        if event_id in self._marks:
            previous_fingerprint, previous_row = self._marks[event_id]
            if previous_fingerprint != fingerprint:
                raise ValueError('A repeated valuation ID cannot change its contents.')
            return deepcopy(previous_row)
        self._ordered(timestamp)
        self._clock = timestamp
        self._price = price_cents
        row = self._record(timestamp, event_id, 'valuation')
        self._marks[event_id] = (fingerprint, row)
        return deepcopy(row)

    def _valuation(self):
        value = value_position(self._position, self._price)
        def money(amount):
            return cents_to_dollars(amount) if amount is not None else None
        market_value = value['market_value_cents']
        return dict(cash=money(self._cash), cash_cents=self._cash, shares=self._position.quantity,
                    cost_basis_cents=self._position.cost_basis_cents,
                    average_cost=(money(self._position.cost_basis_cents) / self._position.quantity
                                  if self._position.quantity and self._position.cost_basis_cents is not None else None),
                    realized=money(value['realized_cents']), unrealized=money(value['unrealized_cents']),
                    total_pnl=money(value['total_pnl_cents']), valuation_available=value['valuation_available'],
                    equity=money(self._cash + market_value) if market_value is not None else None,
                    mark_price=money(self._price))

    def _record(self, timestamp, event_id, source):
        row = dict(run_id=self.run_id, event_id=event_id, timestamp=_text(timestamp), source=source, **self._valuation())
        self._history.append(row)
        return row

    def snapshot(self):
        return deepcopy(dict(run_id=self.run_id, symbol=self.symbol, execution=self.execution,
                             initial_cash=cents_to_dollars(self._initial), **self._valuation(),
                             orders=self._orders, pnl_history=self._history,
                             assumptions=dict(long_only=True, whole_shares=True, fees=0, slippage=0,
                                              money_rounding='ROUND_HALF_UP to cents', cost_basis='weighted average')))

    def current(self):
        """Small immutable-by-copy view for a runner; does not copy the audit history."""
        return dict(**self._valuation(), pending_orders=len(self._pending))
