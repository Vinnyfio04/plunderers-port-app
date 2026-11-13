"""Fixed provider replies through POST /api/decisions; no network or orders."""
import base64
import json
import os
from pathlib import Path
import sqlite3
import struct
import sys
from unittest.mock import patch
import zlib

from backend.market_store import MarketRecorder
from backend.paper_trading import PaperAccount


def png_url() -> str:
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))
    width, height = 400, 240
    raw = b"".join(b"\0" + b"\xff\xff\xff" * width for _ in range(height))
    image = (b"\x89PNG\r\n\x1a\n"
             + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
             + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return "data:image/png;base64," + base64.b64encode(image).decode()


def run():
    path = Path("backend/data/decision-review-test.sqlite3").resolve()
    if path.exists():
        raise SystemExit(f"Refusing existing disposable database: {path}")
    with MarketRecorder(path):
        pass
    with PaperAccount(path, 1000):
        pass
    os.environ.update(MARKET_DATABASE=str(path), MARKET_LIVE_FEED="0",
                      DECISION_PROVIDER="test",
                      DECISION_CAPTURE_DIR=str(path.parent / "decision-captures-review-test"))
    from backend import main
    for window in (1, 2):
        main.indicator_store.create("AAPL", "1m", f"SMA {window}", "sma", {"window": window})
    image = png_url()
    base = "2026-11-09T14:"
    closes = [14, 11, 13]  # TEST DATA: fast SMA crosses upward at 14:32.
    candles = [{"timestamp": f"{base}{30+i:02d}:00Z", "open": price,
                "high": price + 1, "low": price - 1, "close": price,
                "volume": 100} for i, price in enumerate(closes)]
    cases = [
        ("agreed", 1000, "accept", True),
        ("reviewer_rejects", 1000, "reject_unsupported_signal", False),
        ("unaffordable_but_accepted", 5, "accept", False),
    ]
    results = []
    for name, cash, verdict, expected in cases:
        main.paper_account.connection.execute(
            "UPDATE paper_accounts SET cash_cents=? WHERE account_id=1", (cash * 100,))
        main.paper_account.connection.commit()
        snapshot = main.decision_store.create_snapshot("AAPL", "1m", candles[-1]["timestamp"], candles)
        calls = []
        def fixed_reply(body, **kwargs):
            calls.append(body)
            return {"model": "fixed-test", "answers": ([
                {"type": "choice", "name": "action", "choice": "buy"},
                {"type": "choice", "name": "crossover", "choice": "upward"},
                {"type": "choice", "name": "evidence", "choice": "sufficient"},
            ] if len(calls) == 1 else [
                {"type": "choice", "name": "verdict", "choice": verdict},
            ])}
        with patch.object(main, "call_decision_provider", side_effect=fixed_reply):
            result = main.create_decision({"snapshot_id": snapshot["snapshot_id"],
                "symbol": "AAPL", "timeframe": "1m", "cutoff": snapshot["cutoff"],
                "image_data_url": image})
        assert len(calls) == 2
        review_data = calls[1]["input"][0]["content"][2]["data"]
        assert review_data["snapshot"] == snapshot
        assert review_data["analyst_answers"] == result["answers"]
        assert calls[0]["input"][0]["content"][1]["image_url"] == image
        assert calls[1]["input"][0]["content"][1]["image_url"] == image
        assert result["eligible_for_automation"] == expected
        with sqlite3.connect(path) as db:
            saved = db.execute("SELECT answers_json,reviewer_answers_json,final_check_json,"
                "eligible_for_automation FROM decision_records WHERE decision_id=?",
                (result["decision_id"],)).fetchone()
            orders = db.execute("SELECT COUNT(*) FROM paper_orders").fetchone()[0]
        assert json.loads(saved[0]) == result["answers"]
        assert json.loads(saved[1]) == result["reviewer_answers"]
        assert json.loads(saved[2]) == result["final_check"]
        assert bool(saved[3]) == expected and orders == 0
        results.append({"case": name, "decision_id": result["decision_id"],
            "snapshot_id": snapshot["snapshot_id"], "cash": cash,
            "price": result["final_check"]["facts"]["price"],
            "analyst": "buy", "reviewer": verdict,
            "eligible": expected, "reasons": result["eligibility_reasons"],
            "saved": True, "orders": orders})
    # A timed-out first call and a malformed second reply both save an ineligible row.
    for name, replies, expected_calls in (
        ("analyst_timeout", [ValueError("Decision provider request failed: timed out")], 1),
        ("invalid_reviewer", [{"model": "fixed-test", "answers": [
            {"name": "action", "choice": "buy"},
            {"name": "crossover", "choice": "upward"},
            {"name": "evidence", "choice": "sufficient"},
        ]}, {"model": "fixed-test", "answers": []}], 2),
    ):
        snapshot = main.decision_store.create_snapshot("AAPL", "1m", candles[-1]["timestamp"], candles)
        with patch.object(main, "call_decision_provider", side_effect=replies) as provider:
            result = main.create_decision({"snapshot_id": snapshot["snapshot_id"],
                "symbol": "AAPL", "timeframe": "1m", "cutoff": snapshot["cutoff"],
                "image_data_url": image})
        assert provider.call_count == expected_calls
        assert not result["eligible_for_automation"]
        with sqlite3.connect(path) as db:
            saved = db.execute("SELECT eligible_for_automation, eligibility_reasons_json "
                "FROM decision_records WHERE decision_id=?", (result["decision_id"],)).fetchone()
        assert saved[0] == 0 and json.loads(saved[1])
        results.append({"case": name, "decision_id": result["decision_id"],
                        "provider_calls": expected_calls, "eligible": False,
                        "reasons": result["eligibility_reasons"], "saved": True})
    print(json.dumps({"label": "TEST DATA — fixed analyst/reviewer replies",
                      "database": str(path), "results": results}, indent=2))


if __name__ == "__main__":
    run()
