"""Disposable reviewed-decision to next-price paper fill integration check."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from backend.check_decision_review import png_url
from backend.decisions import DecisionStore, decode_png
from backend.indicators import IndicatorStore
from backend.market_store import MarketRecorder
from backend.paper_trading import PaperAccount


DATABASE = Path("backend/data/automation-test.sqlite3").resolve()
CAPTURES = Path("backend/data/decision-captures-automation-test").resolve()


def make_decision(store, snapshot, eligible, verdict):
    return store.save_decision(
        snapshot=snapshot, image=decode_png(png_url()), provider="fixed-test",
        model="fixed-analyst", reviewer_model="fixed-reviewer",
        answers=[{"name": "action", "choice": "buy"},
                 {"name": "crossover", "choice": "upward"},
                 {"name": "evidence", "choice": "sufficient"}],
        reviewer_answers=[{"name": "verdict", "choice": verdict}],
        final_check={"passed": eligible}, eligible=eligible,
        reasons=[] if eligible else ["Reviewer veto"], paper_orders_unchanged=True,
    )


def main():
    if DATABASE.exists():
        raise FileExistsError(DATABASE)
    with MarketRecorder(DATABASE):
        pass
    with PaperAccount(DATABASE, 1000) as paper, IndicatorStore(DATABASE) as indicators:
        indicators.create("AAPL", "1m", "Fast SMA", "sma", {"window": 1})
        indicators.create("AAPL", "1m", "Slow SMA", "sma", {"window": 2})
        decisions = DecisionStore(DATABASE, indicators, paper, CAPTURES)
        closes = [14, 11, 13]
        candles = [{"timestamp": f"2026-11-09T14:{30+i:02d}:00Z",
                    "open": p, "high": p+1, "low": p-1, "close": p,
                    "volume": 100} for i, p in enumerate(closes)]
        config = paper.set_automation(symbol="AAPL", interval="1m", enabled=True, order_size=4)
        snapshot = decisions.create_snapshot("AAPL", "1m", candles[-1]["timestamp"], candles)
        approved = make_decision(decisions, snapshot, True, "accept")
        params = dict(decision_id=approved["decision_id"], symbol="AAPL", interval="1m",
                      candle=snapshot["cutoff"], generation=config["generation"])
        claim = paper.claim_automation_candle(symbol="AAPL",interval="1m",
            candle=snapshot["cutoff"],generation=config["generation"])
        duplicate_claim = paper.claim_automation_candle(symbol="AAPL",interval="1m",
            candle=snapshot["cutoff"],generation=config["generation"])
        assert claim["claimed"] and not duplicate_claim["claimed"]
        first = paper.submit_automation_decision(**params)
        second = paper.submit_automation_decision(**params)
        assert first == second and first["status"] == "pending"
        before = paper.snapshot("AAPL")
        assert before["cash"] == 1000 and before["shares"] == 0
        arrival = datetime.now(timezone.utc)
        with MarketRecorder(DATABASE) as recorder:
            stored = recorder.record_message({"id": "AAPL", "time": int(arrival.timestamp()*1000),
                "price": 100, "test_data": True}, arrival, ticker="AAPL")
        filled = paper.process_market_observation(symbol="AAPL", price=100,
            observation_id=stored.observation_id, receipt_id=stored.receipt_id,
            arrival_time=arrival, source="TEST DATA — automation next price")
        assert len(filled) == 1 and filled[0]["status"] == "filled"
        after = paper.snapshot("AAPL")
        assert after["cash"] == 600 and after["shares"] == 4
        assert after["orders"][0]["decision_id"] == approved["decision_id"]
        assert after["pnl_history"][0]["decision_id"] == approved["decision_id"]
        assert paper.submit_automation_decision(**params)["status"] == "filled"
        veto_candle = {**candles[-1], "timestamp": "2026-11-09T14:33:00Z"}
        veto_snapshot = decisions.create_snapshot("AAPL", "1m", veto_candle["timestamp"], candles+[veto_candle])
        veto = make_decision(decisions, veto_snapshot, False, "reject_unsupported_signal")
        rejected = paper.submit_automation_decision(decision_id=veto["decision_id"],
            symbol="AAPL", interval="1m", candle=veto_snapshot["cutoff"], generation=config["generation"])
        assert rejected["status"] == "skipped"
        assert paper.snapshot("AAPL")["cash"] == 600 and paper.snapshot("AAPL")["shares"] == 4
        stop_candle = {**veto_candle, "timestamp": "2026-11-09T14:34:00Z"}
        stop_snapshot = decisions.create_snapshot("AAPL", "1m", stop_candle["timestamp"], candles+[veto_candle,stop_candle])
        stop_decision = make_decision(decisions, stop_snapshot, True, "accept")
        awaiting = paper.submit_automation_decision(decision_id=stop_decision["decision_id"],
            symbol="AAPL", interval="1m", candle=stop_snapshot["cutoff"], generation=config["generation"])
        assert awaiting["status"] == "pending"
        paper.set_automation(symbol="AAPL", interval="1m", enabled=False, order_size=4)
        stopped_pending = paper.automation_event(awaiting["automation_key"])["status"]
        assert stopped_pending == "skipped"
        later = datetime.now(timezone.utc)
        with MarketRecorder(DATABASE) as recorder:
            later_stored = recorder.record_message({"id":"AAPL", "time":int(later.timestamp()*1000),
                "price": 101, "test_data": True}, later, ticker="AAPL")
        stopped_fills = paper.process_market_observation(symbol="AAPL", price=101,
            observation_id=later_stored.observation_id, receipt_id=later_stored.receipt_id,
            arrival_time=later, source="TEST DATA — price after Stop")
        assert stopped_fills == []
        assert paper.submit_automation_decision(decision_id=approved["decision_id"],
            symbol="AAPL", interval="1m", candle="2026-11-09T14:35:00Z",
            generation=config["generation"])["status"] == "skipped"
        decisions.close()
    with PaperAccount(DATABASE, 1000) as reopened:
        assert not reopened.claim_automation_candle(symbol="AAPL",interval="1m",
            candle=snapshot["cutoff"],generation=config["generation"])["claimed"]
        state = reopened.snapshot("AAPL")
        with sqlite3.connect(DATABASE) as db:
            counts = {name: db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                      for name in ("paper_orders", "paper_fills", "paper_pnl_history", "paper_automation_events")}
            links = db.execute("SELECT f.decision_id,p.decision_id FROM paper_fills f JOIN paper_pnl_history p USING(fill_id)").fetchone()
        assert state["cash"] == 600 and state["shares"] == 4
        assert counts == {"paper_orders":2,"paper_fills":1,"paper_pnl_history":1,"paper_automation_events":4}
        assert links == (approved["decision_id"], approved["decision_id"])
    print(json.dumps({"label":"TEST DATA — reviewed paper automation", "database":str(DATABASE),
        "approved_decision":approved["decision_id"], "first":first,"retry":second,
        "fill":filled,"veto_decision":veto["decision_id"],"veto":rejected,
        "stopped_pending":stopped_pending,
        "fills_after_stop_price":len(stopped_fills),
        "cash":state["cash"],"shares":state["shares"],"counts":counts}, indent=2))


if __name__ == "__main__":
    main()
