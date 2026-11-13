import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from backend.market_store import MarketRecorder
from backend.paper_trading import PaperAccount, execute_paper_action


TEST_LABEL = "TEST DATA — paper account execution fixture"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()
    database = args.database.expanduser().resolve()
    if database.exists():
        raise FileExistsError(database)
    start = datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)

    with MarketRecorder(database) as recorder, PaperAccount(database, 1000) as account:
        buy = execute_paper_action(
            account, request_id="buy-4", symbol="AAPL", action="buy",
            quantity=4, submitted_at=start,
        )
        buy_retry = execute_paper_action(
            account, request_id="buy-4", symbol="AAPL", action="buy",
            quantity=4, submitted_at=start,
        )
        first = recorder.record_message(
            {"id": "AAPL", "time": int((start + timedelta(seconds=1)).timestamp() * 1000), "price": 100, "test_data_label": TEST_LABEL},
            start + timedelta(seconds=1),
        )
        account.process_market_observation(
            symbol="AAPL", price=100, observation_id=first.observation_id,
            receipt_id=first.receipt_id, arrival_time=start + timedelta(seconds=1),
            source=TEST_LABEL,
        )
        after_buy = account.snapshot("AAPL")

        execute_paper_action(
            account, request_id="sell-1", symbol="AAPL", action="sell",
            quantity=1, submitted_at=start + timedelta(seconds=2),
        )
        second = recorder.record_message(
            {"id": "AAPL", "time": int((start + timedelta(seconds=3)).timestamp() * 1000), "price": 110, "test_data_label": TEST_LABEL},
            start + timedelta(seconds=3),
        )
        account.process_market_observation(
            symbol="AAPL", price=110, observation_id=second.observation_id,
            receipt_id=second.receipt_id, arrival_time=start + timedelta(seconds=3),
            source=TEST_LABEL,
        )
        after_sell = account.snapshot("AAPL")

        execute_paper_action(
            account, request_id="close", symbol="AAPL", action="close",
            submitted_at=start + timedelta(seconds=4),
        )
        third = recorder.record_message(
            {"id": "AAPL", "time": int((start + timedelta(seconds=5)).timestamp() * 1000), "price": 105, "test_data_label": TEST_LABEL},
            start + timedelta(seconds=5),
        )
        account.process_market_observation(
            symbol="AAPL", price=105, observation_id=third.observation_id,
            receipt_id=third.receipt_id, arrival_time=start + timedelta(seconds=5),
            source=TEST_LABEL,
        )
        after_close = account.snapshot("AAPL")
        rejected = execute_paper_action(
            account, request_id="sell-empty", symbol="AAPL", action="sell",
            quantity=1, submitted_at=start + timedelta(seconds=6),
        )
        zero_quantity = execute_paper_action(
            account, request_id="zero", symbol="AAPL", action="buy",
            quantity=0, submitted_at=start + timedelta(seconds=7),
        )
        fractional_quantity = execute_paper_action(
            account, request_id="fractional", symbol="AAPL", action="buy",
            quantity=1.5, submitted_at=start + timedelta(seconds=8),
        )
        hold = execute_paper_action(
            account, request_id="hold", symbol="AAPL", action="hold",
            submitted_at=start + timedelta(seconds=9),
        )
        wait = execute_paper_action(
            account, request_id="wait", symbol="AAPL", action="wait",
            submitted_at=start + timedelta(seconds=10),
        )

    with PaperAccount(database, 1) as reopened:
        final = reopened.snapshot("AAPL")
    fills = [order for order in final["orders"] if order["fill"] is not None]
    checks = {
        "buy_pending_before_price": buy["status"] == "pending",
        "retry_is_idempotent": buy_retry["status"] == "idempotent_replay",
        "after_buy": after_buy["cash"] == 600 and after_buy["shares"] == 4,
        "after_sell": after_sell["cash"] == 710 and after_sell["shares"] == 3,
        "after_close": after_close["cash"] == 1025 and after_close["shares"] == 0,
        "empty_sale_rejected": rejected["status"] == "rejected",
        "zero_quantity_rejected": zero_quantity["status"] == "rejected",
        "fractional_quantity_rejected": fractional_quantity["status"] == "rejected",
        "hold_and_wait_create_no_orders": hold["order"] is None and wait["order"] is None,
        "exactly_three_fills_after_restart": len(fills) == 3,
        "final_account_after_restart": final["cash"] == 1025 and final["shares"] == 0,
    }
    print(json.dumps({
        "data_label": TEST_LABEL,
        "database": str(database),
        "states": {"after_buy": after_buy, "after_sell": after_sell, "after_close": after_close, "after_restart": final},
        "checks": checks,
    }, indent=2, sort_keys=True))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
