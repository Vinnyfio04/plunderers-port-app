"""Shared, side-effect-free long-only accounting in integer cents."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


def dollars_to_cents(value: Any) -> int:
    try:
        amount = Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as error:
        raise ValueError('price must be a positive number') from error
    if not amount.is_finite() or amount <= 0:
        raise ValueError('price must be a positive number')
    return int(amount * 100)


def cents_to_dollars(value: int) -> float:
    return float(Decimal(value) / Decimal(100))


def _integer(value, name, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f'{name} must be an integer >= {minimum}.')


@dataclass(frozen=True)
class Position:
    quantity: int = 0
    cost_basis_cents: int | None = 0
    realized_pnl_cents: int | None = 0

    def __post_init__(self):
        _integer(self.quantity, 'Shares')
        if self.cost_basis_cents is not None:
            _integer(self.cost_basis_cents, 'Cost basis')
        if self.realized_pnl_cents is not None and (isinstance(self.realized_pnl_cents, bool) or not isinstance(self.realized_pnl_cents, int)):
            raise ValueError('Realized P&L must be integer cents or unknown.')


@dataclass(frozen=True)
class FillState:
    cash_cents: int
    position: Position


class FillRejected(ValueError):
    pass


def quote_entry(price, quantity):
    """Indicative entry cost using the same money conversion as actual fills."""
    _integer(quantity, 'Quantity', 1)
    cents = dollars_to_cents(price)
    return dict(price_cents=cents, estimated_cost_cents=cents * quantity)


def apply_fill(cash_cents: int, position: Position, side: str, quantity: int, price_cents: int) -> FillState:
    """Return a new state or reject; never mutate the caller's state or database."""
    _integer(cash_cents, 'Cash')
    _integer(quantity, 'Quantity', 1)
    _integer(price_cents, 'Price', 1)
    if side not in ('buy', 'sell'):
        raise ValueError('Fill side must be buy or sell.')
    total = price_cents * quantity
    shares = position.quantity
    if side == 'buy' and total > cash_cents:
        raise FillRejected(f'Insufficient cash at fill: requires ${total / 100:.2f}, available ${cash_cents / 100:.2f}.')
    if side == 'sell' and quantity > shares:
        raise FillRejected(f'Insufficient shares at fill: requested {quantity}, held {shares}.')
    basis, realized = position.cost_basis_cents, position.realized_pnl_cents
    if shares == 0:
        basis = 0
        realized = 0 if realized is None else realized  # preserve legacy flat-account behavior
    next_cash = cash_cents - total if side == 'buy' else cash_cents + total
    next_shares = shares + quantity if side == 'buy' else shares - quantity
    if side == 'buy':
        next_basis = None if basis is None else basis + total
        next_realized = realized
    elif basis is None or realized is None:
        next_basis = None if next_shares else 0
        next_realized = None
    else:
        removed_basis = basis if quantity == shares else int(
            (Decimal(basis) * quantity / shares).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        next_basis = basis - removed_basis
        next_realized = realized + total - removed_basis
    return FillState(next_cash, Position(next_shares, next_basis, next_realized))


def value_position(position: Position, price_cents: int | None) -> dict:
    if price_cents is not None:
        _integer(price_cents, 'Price', 1)
    shares, basis, realized = position.quantity, position.cost_basis_cents, position.realized_pnl_cents
    available = realized is not None and (shares == 0 or (basis is not None and price_cents is not None))
    market_value = shares * price_cents if shares and price_cents is not None else 0 if not shares else None
    unrealized = market_value - basis if available and shares else 0 if available else None
    return dict(average_cost_cents=basis / shares if shares and basis is not None else None,
                realized_cents=realized, unrealized_cents=unrealized,
                total_pnl_cents=realized + unrealized if available else None,
                market_value_cents=market_value, valuation_available=available)
