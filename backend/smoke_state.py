"""Read direct SQLite state for the offline browser SmokeTest."""

import argparse
import json
from pathlib import Path
import sqlite3


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()
    with sqlite3.connect(args.database) as db:
        db.row_factory = sqlite3.Row
        account = db.execute("SELECT cash_cents FROM paper_accounts WHERE account_id=1").fetchone()
        position = db.execute("SELECT quantity,realized_pnl_cents FROM paper_positions WHERE account_id=1 AND symbol='AAPL'").fetchone()
        pnl = db.execute("SELECT * FROM paper_pnl_history WHERE account_id=1 AND symbol='AAPL' ORDER BY pnl_id DESC LIMIT 1").fetchone()
        indicators = [dict(row) for row in db.execute(
            "SELECT name,settings_json FROM indicator_instances WHERE symbol='AAPL' AND timeframe='1m' ORDER BY indicator_id")]
        result = {
            "cash": account["cash_cents"] / 100,
            "shares": position["quantity"] if position else 0,
            "realized": position["realized_pnl_cents"] / 100 if position else 0,
            "unrealized": pnl["unrealized_cents"] / 100 if pnl and pnl["unrealized_cents"] is not None else None,
            "fills": db.execute("SELECT COUNT(*) FROM paper_fills").fetchone()[0],
            "orders": db.execute("SELECT COUNT(*) FROM paper_orders").fetchone()[0],
            "observations": db.execute("SELECT COUNT(*) FROM observations").fetchone()[0],
            "automation": [dict(row) for row in db.execute(
                "SELECT candle_utc,status,reason,decision_id FROM paper_automation_events ORDER BY candle_utc")],
            "indicators": [{"name": item["name"], "settings": json.loads(item["settings_json"])} for item in indicators],
        }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
