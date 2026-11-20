from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import hashlib
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any
from backend.accounting import (
    FillRejected, Position, apply_fill, cents_to_dollars, dollars_to_cents, value_position,
)


PAPER_SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_accounts (
    account_id INTEGER PRIMARY KEY CHECK (account_id = 1),
    initial_cash_cents INTEGER NOT NULL,
    cash_cents INTEGER NOT NULL,
    created_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_positions (
    account_id INTEGER NOT NULL REFERENCES paper_accounts(account_id),
    symbol TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity >= 0),
    cost_basis_cents INTEGER,
    realized_pnl_cents INTEGER,
    updated_at_utc TEXT NOT NULL,
    PRIMARY KEY (account_id, symbol)
);

CREATE TABLE IF NOT EXISTS paper_market_events (
    market_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_id INTEGER NOT NULL REFERENCES observations(observation_id),
    receipt_id INTEGER NOT NULL REFERENCES receipts(receipt_id),
    symbol TEXT NOT NULL,
    price_cents INTEGER NOT NULL CHECK (price_cents > 0),
    arrival_time_utc TEXT NOT NULL,
    source TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_orders (
    order_id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL UNIQUE,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('buy', 'sell', 'close')),
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    quantity INTEGER,
    submission_time_utc TEXT NOT NULL,
    submission_event_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'filled', 'rejected')),
    rejection_reason TEXT,
    decision_id TEXT,
    automation_key TEXT,
    automation_generation INTEGER,
    decision_deadline_utc TEXT
);

CREATE TABLE IF NOT EXISTS paper_fills (
    fill_id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL UNIQUE REFERENCES paper_orders(order_id),
    price_cents INTEGER NOT NULL,
    observation_id INTEGER NOT NULL REFERENCES observations(observation_id),
    receipt_id INTEGER NOT NULL REFERENCES receipts(receipt_id),
    market_event_id INTEGER NOT NULL REFERENCES paper_market_events(market_event_id),
    execution_time_utc TEXT NOT NULL,
    decision_id TEXT
);

CREATE TABLE IF NOT EXISTS paper_pnl_history (
    pnl_id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES paper_accounts(account_id),
    symbol TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('fill', 'completed_candle')),
    event_key TEXT NOT NULL,
    event_time_utc TEXT NOT NULL,
    price_cents INTEGER,
    valuation_source TEXT NOT NULL,
    fill_id INTEGER REFERENCES paper_fills(fill_id),
    market_event_id INTEGER REFERENCES paper_market_events(market_event_id),
    observation_id INTEGER REFERENCES observations(observation_id),
    receipt_id INTEGER REFERENCES receipts(receipt_id),
    cash_cents INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    average_cost_cents REAL,
    cumulative_realized_cents INTEGER,
    unrealized_cents INTEGER,
    total_pnl_cents INTEGER,
    valuation_available INTEGER NOT NULL CHECK (valuation_available IN (0, 1)),
    decision_id TEXT,
    UNIQUE (account_id, symbol, event_key)
);

CREATE INDEX IF NOT EXISTS idx_paper_pending
    ON paper_orders(symbol, status, order_id);
CREATE INDEX IF NOT EXISTS idx_paper_pnl_symbol
    ON paper_pnl_history(account_id, symbol, pnl_id);

CREATE TABLE IF NOT EXISTS paper_automation_settings (
    account_id INTEGER NOT NULL,
    strategy TEXT NOT NULL,
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0,
    generation INTEGER NOT NULL DEFAULT 0,
    order_size INTEGER NOT NULL DEFAULT 1,
    updated_at_utc TEXT NOT NULL,
    PRIMARY KEY (account_id, strategy, symbol, interval)
);
CREATE TABLE IF NOT EXISTS paper_automation_events (
    automation_key TEXT PRIMARY KEY,
    account_id INTEGER NOT NULL,
    strategy TEXT NOT NULL,
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    candle_utc TEXT NOT NULL,
    decision_id TEXT,
    status TEXT NOT NULL,
    reason TEXT,
    order_id INTEGER,
    created_at_utc TEXT NOT NULL,
    UNIQUE (account_id, strategy, symbol, interval, candle_utc)
);
"""


def utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("time must include a timezone")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ExecutionRequest:
    request_id: str
    symbol: str
    action: str
    quantity: Any
    submitted_at: datetime


class PaperAccount:
    def __init__(self, database_path: str | Path, starting_cash: Any = "10000"):
        self.path = Path(database_path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.executescript(PAPER_SCHEMA)
        self._ensure_position_columns()
        self._ensure_automation_columns()
        self._lock = RLock()
        initial_cash = dollars_to_cents(starting_cash)
        now = utc_text(datetime.now(timezone.utc))
        with self.connection:
            self.connection.execute(
                """
                INSERT OR IGNORE INTO paper_accounts (
                    account_id, initial_cash_cents, cash_cents, created_at_utc
                ) VALUES (1, ?, ?, ?)
                """,
                (initial_cash, initial_cash, now),
            )

    def _ensure_position_columns(self) -> None:
        """Migrate databases created before cost basis and P&L were introduced."""
        columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(paper_positions)")
        }
        if "cost_basis_cents" not in columns:
            self.connection.execute(
                "ALTER TABLE paper_positions ADD COLUMN cost_basis_cents INTEGER"
            )
        if "realized_pnl_cents" not in columns:
            self.connection.execute(
                "ALTER TABLE paper_positions ADD COLUMN realized_pnl_cents INTEGER"
            )

    def _ensure_automation_columns(self) -> None:
        for table, definitions in {
            "paper_orders": {"decision_id": "TEXT", "automation_key": "TEXT",
                             "automation_generation": "INTEGER", "decision_deadline_utc": "TEXT"},
            "paper_fills": {"decision_id": "TEXT"},
            "paper_pnl_history": {"decision_id": "TEXT"},
        }.items():
            present = {row["name"] for row in self.connection.execute(f"PRAGMA table_info({table})")}
            for name, definition in definitions.items():
                if name not in present:
                    self.connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    def __enter__(self) -> "PaperAccount":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def submit(self, request: ExecutionRequest) -> dict[str, Any]:
        request_id = str(request.request_id).strip()
        symbol = str(request.symbol).strip().upper()
        action = str(request.action).strip().lower()
        if not request_id or len(request_id) > 128:
            raise ValueError("request_id is required and must be at most 128 characters")
        if not symbol:
            raise ValueError("symbol is required")
        if action in {"hold", "wait"}:
            return {
                "request_id": request_id,
                "action": action,
                "status": "no_order",
                "message": (
                    "Hold keeps the existing position."
                    if action == "hold"
                    else "Wait stays in cash."
                ),
                "order": None,
            }
        if action not in {"buy", "sell", "close"}:
            raise ValueError("action must be buy, sell, close, hold, or wait")

        with self._lock:
            existing = self.connection.execute(
                "SELECT order_id FROM paper_orders WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if existing is not None:
                return {
                    "request_id": request_id,
                    "action": action,
                    "status": "idempotent_replay",
                    "message": "Existing order returned; no duplicate order or fill was created.",
                    "order": self._order(int(existing["order_id"])),
                }

            shares = self._shares(symbol)
            side = "buy" if action == "buy" else "sell"
            quantity: int | None
            rejection: str | None = None
            if action == "close":
                quantity = shares
                if quantity == 0:
                    rejection = "Cannot close an empty position."
            elif isinstance(request.quantity, bool) or not isinstance(request.quantity, int):
                quantity = None
                rejection = "Quantity must be a whole number of shares."
            else:
                quantity = request.quantity
                if quantity <= 0:
                    rejection = "Quantity must be greater than zero."
                elif side == "sell" and quantity > shares:
                    rejection = f"Cannot sell {quantity} shares; position holds {shares}."

            marker = int(
                self.connection.execute(
                    "SELECT COALESCE(MAX(market_event_id), 0) FROM paper_market_events"
                ).fetchone()[0]
            )
            status = "rejected" if rejection else "pending"
            with self.connection:
                cursor = self.connection.execute(
                    """
                    INSERT INTO paper_orders (
                        request_id, symbol, action, side, quantity,
                        submission_time_utc, submission_event_id, status,
                        rejection_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        request_id,
                        symbol,
                        action,
                        side,
                        quantity,
                        utc_text(request.submitted_at),
                        marker,
                        status,
                        rejection,
                    ),
                )
            order = self._order(int(cursor.lastrowid))
            return {
                "request_id": request_id,
                "action": action,
                "status": status,
                "message": rejection or "Order accepted and pending the next eligible price.",
                "order": order,
            }

    @staticmethod
    def automation_key(strategy: str, symbol: str, interval: str, candle: str) -> str:
        raw = f"1|{strategy}|{symbol.upper()}|{interval}|{candle}".encode()
        return "auto:" + hashlib.sha256(raw).hexdigest()

    def automation_status(self, symbol: str, interval: str, strategy: str = "sma-crossover") -> dict[str, Any]:
        symbol = symbol.strip().upper()
        with self._lock:
            setting = self.connection.execute(
                "SELECT * FROM paper_automation_settings WHERE account_id=1 AND strategy=? AND symbol=? AND interval=?",
                (strategy, symbol, interval),
            ).fetchone()
            events = self.connection.execute(
                "SELECT * FROM paper_automation_events WHERE account_id=1 AND strategy=? AND symbol=? AND interval=? ORDER BY created_at_utc DESC LIMIT 20",
                (strategy, symbol, interval),
            ).fetchall()
        return {"enabled": bool(setting["enabled"]) if setting else False,
                "generation": int(setting["generation"]) if setting else 0,
                "order_size": int(setting["order_size"]) if setting else 1,
                "account_id": 1, "strategy": strategy, "symbol": symbol,
                "interval": interval, "events": [dict(row) for row in events]}

    def set_automation(self, *, symbol: str, interval: str, enabled: bool,
                       order_size: int = 1, strategy: str = "sma-crossover") -> dict[str, Any]:
        symbol = symbol.strip().upper()
        if not symbol or not interval or not strategy or isinstance(order_size, bool) or not isinstance(order_size, int) or order_size < 1:
            raise ValueError("Symbol, interval, strategy, and a positive whole-share order size are required.")
        now = utc_text(datetime.now(timezone.utc))
        with self._lock, self.connection:
            self.connection.execute(
                """INSERT INTO paper_automation_settings
                (account_id,strategy,symbol,interval,enabled,generation,order_size,updated_at_utc)
                VALUES (1,?,?,?,?,1,?,?)
                ON CONFLICT(account_id,strategy,symbol,interval) DO UPDATE SET
                enabled=excluded.enabled, generation=generation+1,
                order_size=excluded.order_size, updated_at_utc=excluded.updated_at_utc""",
                (strategy, symbol, interval, int(enabled), order_size, now),
            )
            if not enabled:
                self.connection.execute("""UPDATE paper_automation_events SET status='skipped',reason='Paper automation stopped during analysis.'
                    WHERE account_id=1 AND strategy=? AND symbol=? AND interval=? AND status='analyzing'""",
                    (strategy,symbol,interval))
                pending = self.connection.execute(
                    """SELECT order_id,automation_key FROM paper_orders WHERE status='pending'
                    AND automation_key IN (SELECT automation_key FROM paper_automation_events
                    WHERE account_id=1 AND strategy=? AND symbol=? AND interval=?)""",
                    (strategy, symbol, interval),
                ).fetchall()
                for row in pending:
                    self.connection.execute("UPDATE paper_orders SET status='rejected',rejection_reason='Paper automation stopped before fill.' WHERE order_id=?", (row["order_id"],))
                    self.connection.execute("UPDATE paper_automation_events SET status='skipped',reason='Paper automation stopped before fill.' WHERE automation_key=?", (row["automation_key"],))
        return self.automation_status(symbol, interval, strategy)

    def record_automation_skip(self, *, symbol: str, interval: str, candle: str,
                               reason: str, strategy: str = "sma-crossover",
                               generation: int | None = None) -> dict[str, Any]:
        symbol = symbol.strip().upper()
        key = self.automation_key(strategy, symbol, interval, candle)
        with self._lock, self.connection:
            setting = self.automation_status(symbol, interval, strategy)
            if not setting["enabled"] or (generation is not None and generation != setting["generation"]):
                reason = "Automation stopped before analysis completed."
            self.connection.execute("UPDATE paper_automation_events SET status='skipped',reason=? WHERE automation_key=? AND status='analyzing'", (reason,key))
            self.connection.execute("""INSERT OR IGNORE INTO paper_automation_events
                (automation_key,account_id,strategy,symbol,interval,candle_utc,status,reason,created_at_utc)
                VALUES (?,1,?,?,?,?,'skipped',?,?)""",
                (key,strategy,symbol,interval,candle,reason,utc_text(datetime.now(timezone.utc))),
            )
        return self.automation_event(key)

    def claim_automation_candle(self, *, symbol: str, interval: str, candle: str,
                                generation: int, strategy: str = "sma-crossover") -> dict[str, Any]:
        symbol = symbol.strip().upper()
        key = self.automation_key(strategy, symbol, interval, candle)
        with self._lock, self.connection:
            setting = self.automation_status(symbol, interval, strategy)
            if not setting["enabled"] or setting["generation"] != generation:
                return {"claimed": False, "reason": "Automation stopped or changed.", "event": self.automation_event(key)}
            cursor = self.connection.execute("""INSERT OR IGNORE INTO paper_automation_events
                (automation_key,account_id,strategy,symbol,interval,candle_utc,status,created_at_utc)
                VALUES (?,1,?,?,?,?,'analyzing',?)""",
                (key,strategy,symbol,interval,candle,utc_text(datetime.now(timezone.utc))))
        return {"claimed": cursor.rowcount == 1, "event": self.automation_event(key)}

    def automation_event(self, key: str) -> dict[str, Any]:
        row = self.connection.execute("SELECT * FROM paper_automation_events WHERE automation_key=?", (key,)).fetchone()
        return dict(row) if row else {}

    def submit_automation_decision(self, *, decision_id: str, symbol: str, interval: str,
                                   candle: str, generation: int,
                                   strategy: str = "sma-crossover") -> dict[str, Any]:
        symbol = symbol.strip().upper()
        key = self.automation_key(strategy, symbol, interval, candle)
        now = datetime.now(timezone.utc)
        with self._lock, self.connection:
            existing = self.automation_event(key)
            if existing and existing["status"] != "analyzing":
                return existing
            setting = self.automation_status(symbol, interval, strategy)
            reason = None
            decision = self.connection.execute("""SELECT d.*,s.snapshot_json FROM decision_records d
                JOIN decision_snapshots s USING(snapshot_id) WHERE d.decision_id=?""", (decision_id,)).fetchone()
            snapshot = json.loads(decision["snapshot_json"]) if decision else None
            if not setting["enabled"] or setting["generation"] != generation:
                reason = "Automation stopped or changed before decision returned."
            elif not decision or not snapshot or snapshot["symbol"] != symbol or snapshot["interval"] != interval or snapshot["cutoff"] != candle or snapshot["paper_position"]["account_id"] != 1:
                reason = "Decision does not match this paper account, symbol, interval, or candle."
            elif not decision["eligible_for_automation"] or not any(a.get("name") == "verdict" and a.get("choice") == "accept" for a in json.loads(decision["reviewer_answers_json"] or "[]")):
                reason = "Analyst/reviewer decision is ineligible or vetoed."
            elif (now - datetime.fromisoformat(decision["created_at_utc"].replace("Z", "+00:00"))).total_seconds() > 300:
                reason = "Decision is older than five minutes."
            status, order_id = "skipped", None
            if not reason:
                action = next((a.get("choice") for a in json.loads(decision["answers_json"]) if a.get("name") == "action"), None)
                if action in ("hold", "wait"):
                    status, reason = "no_order", f"{action} creates no paper order."
                elif action not in ("buy", "sell", "close"):
                    reason = "Analyst action is invalid."
                else:
                    shares = self._shares(symbol)
                    quantity = shares if action == "close" else setting["order_size"]
                    marker = int(self.connection.execute("SELECT COALESCE(MAX(market_event_id),0) FROM paper_market_events").fetchone()[0])
                    cursor = self.connection.execute("""INSERT INTO paper_orders
                        (request_id,symbol,action,side,quantity,submission_time_utc,
                         submission_event_id,status,decision_id,automation_key,
                         automation_generation,decision_deadline_utc)
                        VALUES (?,?,?,?,?, ?,?,'pending',?,?,?,?)""",
                        (key,symbol,action,"buy" if action == "buy" else "sell",quantity,
                         utc_text(now),marker,decision_id,key,generation,
                         utc_text(datetime.fromisoformat(decision["created_at_utc"].replace("Z", "+00:00"))+timedelta(minutes=5))),
                    )
                    order_id = int(cursor.lastrowid)
                    status = "pending"
            self.connection.execute("""INSERT INTO paper_automation_events
                (automation_key,account_id,strategy,symbol,interval,candle_utc,decision_id,status,reason,order_id,created_at_utc)
                VALUES (?,1,?,?,?,?,?,?,?,?,?) ON CONFLICT(automation_key) DO UPDATE SET
                decision_id=excluded.decision_id,status=excluded.status,
                reason=excluded.reason,order_id=excluded.order_id""",
                (key,strategy,symbol,interval,candle,decision_id,status,reason,order_id,utc_text(now)),
            )
        return self.automation_event(key)

    def process_market_observation(
        self,
        *,
        symbol: str,
        price: Any,
        observation_id: int,
        receipt_id: int,
        arrival_time: datetime,
        source: str,
    ) -> list[dict[str, Any]]:
        normalized_symbol = symbol.strip().upper()
        price_cents = dollars_to_cents(price)
        execution_time = utc_text(arrival_time)
        results: list[dict[str, Any]] = []
        with self._lock, self.connection:
            existing_event = self.connection.execute(
                """
                SELECT market_event_id FROM paper_market_events
                WHERE receipt_id = ? AND symbol = ? AND source = ?
                ORDER BY market_event_id LIMIT 1
                """,
                (receipt_id, normalized_symbol, source),
            ).fetchone()
            if existing_event is not None:
                return results
            event_cursor = self.connection.execute(
                """
                INSERT INTO paper_market_events (
                    observation_id, receipt_id, symbol, price_cents,
                    arrival_time_utc, source
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    observation_id,
                    receipt_id,
                    normalized_symbol,
                    price_cents,
                    execution_time,
                    source,
                ),
            )
            market_event_id = int(event_cursor.lastrowid)
            pending = self.connection.execute(
                """
                SELECT * FROM paper_orders
                WHERE symbol = ? AND status = 'pending'
                  AND submission_event_id < ?
                ORDER BY order_id
                """,
                (normalized_symbol, market_event_id),
            ).fetchall()
            for order in pending:
                quantity = int(order["quantity"])
                cash_cents = int(
                    self.connection.execute(
                        "SELECT cash_cents FROM paper_accounts WHERE account_id = 1"
                    ).fetchone()[0]
                )
                position = Position(**self._position(normalized_symbol))
                rejection = None
                if order["automation_key"]:
                    event = self.automation_event(order["automation_key"])
                    setting = self.automation_status(normalized_symbol, event["interval"], event["strategy"])
                    if not setting["enabled"] or setting["generation"] != order["automation_generation"]:
                        rejection = "Paper automation stopped or changed before fill."
                    elif utc_text(datetime.now(timezone.utc)) > order["decision_deadline_utc"]:
                        rejection = "Decision expired before the next eligible price."
                if not rejection:
                    try:
                        filled_state = apply_fill(cash_cents, position, order['side'], quantity, price_cents)
                    except FillRejected as error:
                        rejection = str(error)
                if rejection:
                    self.connection.execute(
                        """
                        UPDATE paper_orders
                        SET status = 'rejected', rejection_reason = ?
                        WHERE order_id = ?
                        """,
                        (rejection, order["order_id"]),
                    )
                    if order["automation_key"]:
                        self.connection.execute("UPDATE paper_automation_events SET status='skipped',reason=? WHERE automation_key=?", (rejection, order["automation_key"]))
                    results.append({"order_id": order["order_id"], "status": "rejected"})
                    continue

                next_cash = filled_state.cash_cents
                next_shares = filled_state.position.quantity
                next_basis = filled_state.position.cost_basis_cents
                next_realized = filled_state.position.realized_pnl_cents
                self.connection.execute(
                    "UPDATE paper_accounts SET cash_cents = ? WHERE account_id = 1",
                    (next_cash,),
                )
                self.connection.execute(
                    """
                    INSERT INTO paper_positions (
                        account_id, symbol, quantity, cost_basis_cents,
                        realized_pnl_cents, updated_at_utc
                    ) VALUES (1, ?, ?, ?, ?, ?)
                    ON CONFLICT(account_id, symbol) DO UPDATE SET
                        quantity = excluded.quantity,
                        cost_basis_cents = excluded.cost_basis_cents,
                        realized_pnl_cents = excluded.realized_pnl_cents,
                        updated_at_utc = excluded.updated_at_utc
                    """,
                    (
                        normalized_symbol,
                        next_shares,
                        next_basis,
                        next_realized,
                        execution_time,
                    ),
                )
                fill_cursor = self.connection.execute(
                    """
                    INSERT INTO paper_fills (
                        order_id, price_cents, observation_id, receipt_id,
                        market_event_id, execution_time_utc, decision_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        order["order_id"],
                        price_cents,
                        observation_id,
                        receipt_id,
                        market_event_id,
                        execution_time,
                        order["decision_id"],
                    ),
                )
                self.connection.execute(
                    "UPDATE paper_orders SET status = 'filled' WHERE order_id = ?",
                    (order["order_id"],),
                )
                if order["automation_key"]:
                    self.connection.execute("UPDATE paper_automation_events SET status='filled',reason=NULL WHERE automation_key=?", (order["automation_key"],))
                fill_id = int(fill_cursor.lastrowid)
                self._insert_pnl_row(
                    event_type="fill",
                    event_key=f"fill:{fill_id}",
                    symbol=normalized_symbol,
                    event_time=execution_time,
                    price_cents=price_cents,
                    valuation_source=source,
                    fill_id=fill_id,
                    market_event_id=market_event_id,
                    observation_id=observation_id,
                    receipt_id=receipt_id,
                    decision_id=order["decision_id"],
                )
                results.append(
                    {
                        "order_id": order["order_id"],
                        "fill_id": fill_id,
                        "status": "filled",
                    }
                )
        return results

    def record_completed_candle_valuation(
        self,
        *,
        event_key: str,
        symbol: str,
        price: Any,
        event_time: datetime,
        source: str,
        observation_id: int | None = None,
        receipt_id: int | None = None,
        market_event_id: int | None = None,
    ) -> dict[str, Any] | None:
        """Append one valuation for an open position; repeat keys are ignored."""
        normalized_symbol = symbol.strip().upper()
        price_cents = dollars_to_cents(price)
        with self._lock, self.connection:
            if self._shares(normalized_symbol) == 0:
                return None
            self._insert_pnl_row(
                event_type="completed_candle",
                event_key=event_key,
                symbol=normalized_symbol,
                event_time=utc_text(event_time),
                price_cents=price_cents,
                valuation_source=source,
                fill_id=None,
                market_event_id=market_event_id,
                observation_id=observation_id,
                receipt_id=receipt_id,
            )
            row = self.connection.execute(
                """
                SELECT * FROM paper_pnl_history
                WHERE account_id = 1 AND symbol = ? AND event_key = ?
                """,
                (normalized_symbol, event_key),
            ).fetchone()
            return self._pnl_row(row)

    def _insert_pnl_row(
        self,
        *,
        event_type: str,
        event_key: str,
        symbol: str,
        event_time: str,
        price_cents: int,
        valuation_source: str,
        fill_id: int | None,
        market_event_id: int | None,
        observation_id: int | None,
        receipt_id: int | None,
        decision_id: str | None = None,
    ) -> None:
        account = self.connection.execute(
            "SELECT cash_cents FROM paper_accounts WHERE account_id = 1"
        ).fetchone()
        position = self._position(symbol)
        quantity = int(position["quantity"])
        basis = position["cost_basis_cents"]
        realized = position["realized_pnl_cents"]
        valuation = value_position(Position(quantity, basis, realized), price_cents)
        average_cost = valuation['average_cost_cents']
        available = valuation['valuation_available']
        unrealized = valuation['unrealized_cents']
        total_pnl = valuation['total_pnl_cents']
        self.connection.execute(
            """
            INSERT INTO paper_pnl_history (
                account_id, symbol, event_type, event_key, event_time_utc,
                price_cents, valuation_source, fill_id, market_event_id,
                observation_id, receipt_id, cash_cents, quantity,
                average_cost_cents, cumulative_realized_cents,
                unrealized_cents, total_pnl_cents, valuation_available, decision_id
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id, symbol, event_key) DO NOTHING
            """,
            (
                symbol,
                event_type,
                event_key,
                event_time,
                price_cents,
                valuation_source,
                fill_id,
                market_event_id,
                observation_id,
                receipt_id,
                int(account["cash_cents"]),
                quantity,
                average_cost,
                realized,
                unrealized,
                total_pnl,
                int(available),
                decision_id,
            ),
        )

    def snapshot(self, symbol: str) -> dict[str, Any]:
        normalized_symbol = symbol.strip().upper()
        with self._lock:
            account = self.connection.execute(
                "SELECT * FROM paper_accounts WHERE account_id = 1"
            ).fetchone()
            orders = self.connection.execute(
                """
                SELECT
                    orders.*,
                    fills.fill_id,
                    fills.price_cents AS fill_price_cents,
                    fills.observation_id,
                    fills.receipt_id,
                    fills.market_event_id,
                    fills.execution_time_utc
                FROM paper_orders AS orders
                LEFT JOIN paper_fills AS fills USING (order_id)
                WHERE orders.symbol = ?
                ORDER BY orders.order_id DESC
                """,
                (normalized_symbol,),
            ).fetchall()
            pnl_rows = self.connection.execute(
                """
                SELECT * FROM paper_pnl_history
                WHERE account_id = 1 AND symbol = ?
                ORDER BY pnl_id
                """,
                (normalized_symbol,),
            ).fetchall()
            position = self._position(normalized_symbol)
            latest = self._pnl_row(pnl_rows[-1]) if pnl_rows else None
            return {
                "account_id": 1,
                "symbol": normalized_symbol,
                "initial_cash": cents_to_dollars(int(account["initial_cash_cents"])),
                "cash": cents_to_dollars(int(account["cash_cents"])),
                "cash_cents": int(account["cash_cents"]),
                "shares": int(position["quantity"]),
                "average_cost": (
                    cents_to_dollars(position["cost_basis_cents"])
                    / int(position["quantity"])
                    if position["cost_basis_cents"] is not None
                    and int(position["quantity"])
                    else None
                ),
                "valuation": latest or {
                    "valuation_available": int(position["quantity"]) == 0,
                    "message": (
                        "No usable valuation price is available for the open position."
                        if int(position["quantity"])
                        else "No open position."
                    ),
                },
                "fill_rule": (
                    "Pending orders fill at the next eligible observed price after "
                    "submission, rounded to cents, with zero fees."
                ),
                "orders": [self._order_row(row) for row in orders],
                "pnl_history": [self._pnl_row(row) for row in pnl_rows],
            }

    def _position(self, symbol: str) -> dict[str, int | None]:
        row = self.connection.execute(
            """
            SELECT quantity, cost_basis_cents, realized_pnl_cents
            FROM paper_positions WHERE account_id = 1 AND symbol = ?
            """,
            (symbol,),
        ).fetchone()
        if row is None:
            return {"quantity": 0, "cost_basis_cents": 0, "realized_pnl_cents": 0}
        return {
            "quantity": int(row["quantity"]),
            "cost_basis_cents": (
                int(row["cost_basis_cents"])
                if row["cost_basis_cents"] is not None else None
            ),
            "realized_pnl_cents": (
                int(row["realized_pnl_cents"])
                if row["realized_pnl_cents"] is not None else None
            ),
        }

    def _shares(self, symbol: str) -> int:
        row = self.connection.execute(
            "SELECT quantity FROM paper_positions WHERE account_id = 1 AND symbol = ?",
            (symbol,),
        ).fetchone()
        return int(row[0]) if row else 0

    @staticmethod
    def _pnl_row(row: sqlite3.Row) -> dict[str, Any]:
        def money(column: str) -> float | None:
            value = row[column]
            return cents_to_dollars(int(value)) if value is not None else None

        average = row["average_cost_cents"]
        return {
            "pnl_id": int(row["pnl_id"]),
            "account_id": int(row["account_id"]),
            "symbol": row["symbol"],
            "event_type": row["event_type"],
            "event_key": row["event_key"],
            "timestamp": row["event_time_utc"],
            "price": money("price_cents"),
            "valuation_source": row["valuation_source"],
            "fill_id": int(row["fill_id"]) if row["fill_id"] is not None else None,
            "decision_id": row["decision_id"],
            "market_event_id": (
                int(row["market_event_id"])
                if row["market_event_id"] is not None else None
            ),
            "observation_id": (
                int(row["observation_id"])
                if row["observation_id"] is not None else None
            ),
            "receipt_id": int(row["receipt_id"]) if row["receipt_id"] is not None else None,
            "cash": money("cash_cents"),
            "shares": int(row["quantity"]),
            "average_cost": float(Decimal(str(average)) / Decimal(100)) if average is not None else None,
            "realized": money("cumulative_realized_cents"),
            "unrealized": money("unrealized_cents"),
            "total_pnl": money("total_pnl_cents"),
            "valuation_available": bool(row["valuation_available"]),
        }

    def _order(self, order_id: int) -> dict[str, Any]:
        row = self.connection.execute(
            """
            SELECT
                orders.*,
                fills.fill_id,
                fills.price_cents AS fill_price_cents,
                fills.observation_id,
                fills.receipt_id,
                fills.market_event_id,
                fills.execution_time_utc
            FROM paper_orders AS orders
            LEFT JOIN paper_fills AS fills USING (order_id)
            WHERE orders.order_id = ?
            """,
            (order_id,),
        ).fetchone()
        return self._order_row(row)

    @staticmethod
    def _order_row(row: sqlite3.Row) -> dict[str, Any]:
        fill = None
        if row["fill_id"] is not None:
            fill = {
                "fill_id": int(row["fill_id"]),
                "price": cents_to_dollars(int(row["fill_price_cents"])),
                "observation_id": int(row["observation_id"]),
                "receipt_id": int(row["receipt_id"]),
                "market_event_id": int(row["market_event_id"]),
                "execution_time": row["execution_time_utc"],
            }
        return {
            "order_id": int(row["order_id"]),
            "request_id": row["request_id"],
            "symbol": row["symbol"],
            "action": row["action"],
            "side": row["side"],
            "quantity": row["quantity"],
            "submission_time": row["submission_time_utc"],
            "status": row["status"],
            "rejection_reason": row["rejection_reason"],
            "decision_id": row["decision_id"],
            "fill": fill,
        }


def execute_paper_action(
    account: PaperAccount,
    *,
    request_id: str,
    symbol: str,
    action: str,
    quantity: Any = None,
    submitted_at: datetime | None = None,
) -> dict[str, Any]:
    """Single reusable entry point for Vue and a future decision agent."""
    request = ExecutionRequest(
        request_id=request_id,
        symbol=symbol,
        action=action,
        quantity=quantity,
        submitted_at=submitted_at or datetime.now(timezone.utc),
    )
    return account.submit(request)
