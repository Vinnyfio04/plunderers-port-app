import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

from backend.market_store import MarketRecorder
from backend.paper_trading import PaperAccount, execute_paper_action


TEST_LABEL = "TEST DATA — P&L history fixture"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()
    database = args.database.expanduser().resolve()
    if database.exists():
        raise FileExistsError(database)
    start = datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)

    def observation(recorder: MarketRecorder, offset: int, price: int):
        event_time = start + timedelta(seconds=offset)
        stored = recorder.record_message(
            {
                "id": "AAPL",
                "time": int(event_time.timestamp() * 1000),
                "price": price,
                "test_data": True,
                "test_data_label": TEST_LABEL,
            },
            event_time,
            ticker="AAPL",
        )
        return event_time, stored

    with MarketRecorder(database) as recorder, PaperAccount(database, 1000) as account:
        execute_paper_action(
            account, request_id="pnl-buy-4", symbol="AAPL", action="buy",
            quantity=4, submitted_at=start,
        )
        event_time, stored = observation(recorder, 1, 100)
        account.process_market_observation(
            symbol="AAPL", price=100, observation_id=stored.observation_id,
            receipt_id=stored.receipt_id, arrival_time=event_time, source=TEST_LABEL,
        )

        event_time, stored = observation(recorder, 2, 110)
        account.record_completed_candle_valuation(
            event_key="completed-candle:AAPL:1m:2026-11-09T15:00:00Z",
            symbol="AAPL", price=110, event_time=event_time, source=TEST_LABEL,
            observation_id=stored.observation_id, receipt_id=stored.receipt_id,
        )
        account.record_completed_candle_valuation(
            event_key="completed-candle:AAPL:1m:2026-11-09T15:00:00Z",
            symbol="AAPL", price=110, event_time=event_time, source=TEST_LABEL,
            observation_id=stored.observation_id, receipt_id=stored.receipt_id,
        )

        execute_paper_action(
            account, request_id="pnl-sell-1", symbol="AAPL", action="sell",
            quantity=1, submitted_at=start + timedelta(seconds=3),
        )
        event_time, stored = observation(recorder, 4, 110)
        account.process_market_observation(
            symbol="AAPL", price=110, observation_id=stored.observation_id,
            receipt_id=stored.receipt_id, arrival_time=event_time, source=TEST_LABEL,
        )

        event_time, stored = observation(recorder, 5, 95)
        account.record_completed_candle_valuation(
            event_key="completed-candle:AAPL:1m:2026-11-09T15:01:00Z",
            symbol="AAPL", price=95, event_time=event_time, source=TEST_LABEL,
            observation_id=stored.observation_id, receipt_id=stored.receipt_id,
        )

        execute_paper_action(
            account, request_id="pnl-close", symbol="AAPL", action="close",
            submitted_at=start + timedelta(seconds=6),
        )
        event_time, stored = observation(recorder, 7, 105)
        account.process_market_observation(
            symbol="AAPL", price=105, observation_id=stored.observation_id,
            receipt_id=stored.receipt_id, arrival_time=event_time, source=TEST_LABEL,
        )
        before_restart = account.snapshot("AAPL")

    sql = sqlite3.connect(database)
    sql.row_factory = sqlite3.Row
    direct_before = [dict(row) for row in sql.execute(
        """
        SELECT pnl_id, event_type, event_key, price_cents, cash_cents, quantity,
               cumulative_realized_cents, unrealized_cents, total_pnl_cents
        FROM paper_pnl_history ORDER BY pnl_id
        """
    )]
    sql.close()

    with PaperAccount(database, 1) as reopened:
        after_restart = reopened.snapshot("AAPL")
    sql = sqlite3.connect(database)
    direct_after_count = sql.execute(
        "SELECT COUNT(*) FROM paper_pnl_history"
    ).fetchone()[0]
    sql.close()

    expected = [
        (600, 4, 0, 0, 0),
        (600, 4, 0, 40, 40),
        (710, 3, 10, 30, 40),
        (710, 3, 10, -15, -5),
        (1025, 0, 25, 0, 25),
    ]
    observed = [
        (row["cash"], row["shares"], row["realized"], row["unrealized"], row["total_pnl"])
        for row in before_restart["pnl_history"]
    ]
    checks = {
        "five_expected_rows": len(observed) == 5,
        "amounts_match": observed == expected,
        "repeat_event_is_single_row": sum(
            row["event_key"] == "completed-candle:AAPL:1m:2026-11-09T15:00:00Z"
            for row in before_restart["pnl_history"]
        ) == 1,
        "direct_sql_matches_api_count": len(direct_before) == len(observed),
        "restart_preserves_rows": after_restart["pnl_history"] == before_restart["pnl_history"],
        "direct_sql_count_after_restart": direct_after_count == 5,
    }
    print(json.dumps({
        "data_label": TEST_LABEL,
        "database": str(database),
        "expected_dollars": expected,
        "observed_dollars": observed,
        "direct_sql_before_restart": direct_before,
        "after_restart": after_restart["pnl_history"],
        "checks": checks,
    }, indent=2, sort_keys=True))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
