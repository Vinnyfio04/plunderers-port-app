import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from backend.decisions import (
    DecisionStore,
    call_decision_provider,
    decode_png,
    decision_request,
    final_rule_check,
    provider_settings,
    review_request,
    validate_answers,
    validate_review,
)
from backend.indicators import (
    INDICATOR_TYPES,
    IndicatorStore,
    indicator_type_contracts,
    instance_with_values,
)
from backend.live_candles import CandleHub
from backend.recorded_history import recorded_history
from backend.yahoo_history import fetch_recent
from backend.market_store import DEFAULT_DATABASE, MarketRecorder
from backend.paper_trading import PaperAccount, dollars_to_cents, execute_paper_action
from backend.replay_session import ReplayEngine, RecordedSessionReader, parse_utc
from backend.timeframe_history import (
    SUPPORTED_TIMEFRAMES,
    Timeframe,
    aggregate_timeframe,
    load_minute_records,
)
from backend.voice import create_live_session, decision_summary, list_decision_summaries


DATABASE_PATH = Path(
    os.getenv("MARKET_DATABASE", str(DEFAULT_DATABASE))
).expanduser().resolve()
with MarketRecorder(DATABASE_PATH):
    pass
paper_account = PaperAccount(
    DATABASE_PATH,
    os.getenv("PAPER_STARTING_CASH", "10000"),
)

app = FastAPI(title="Live Market Workplace API")
candle_hub = CandleHub(database_path=DATABASE_PATH, paper_account=paper_account)
replay_reader = RecordedSessionReader(candle_hub.database_path)
replay_engine = ReplayEngine(candle_hub.database_path)
indicator_store = IndicatorStore(candle_hub.database_path)
decision_store = DecisionStore(
    candle_hub.database_path,
    indicator_store,
    paper_account,
    os.getenv(
        "DECISION_CAPTURE_DIR",
        str(Path(__file__).resolve().parent / "data" / "decision-captures"),
    ),
)
LIVE_FEED_ENABLED = os.getenv("MARKET_LIVE_FEED", "1") == "1"
PAPER_FIXTURE_ENABLED = os.getenv("MARKET_PAPER_FIXTURE", "0") == "1"

CANDLE_FILE = Path(
    os.getenv(
        "MARKET_CANDLE_FILE",
        str(
            Path(__file__).resolve().parent.parent
            / "prompts"
            / "data"
            / "sample-candles.csv"
        ),
    )
).expanduser().resolve()
HISTORY_SYMBOL = "AAPL"
history_refresh_task = None


@app.on_event('startup')
async def start_history_refresh():
    global history_refresh_task
    # Fixtures and explicitly offline runs never contact Yahoo.
    if (not LIVE_FEED_ENABLED or os.getenv('MARKET_CANDLE_FILE')
            or os.getenv('MARKET_TEST_FEED', '0') == '1'):
        return
    await asyncio.to_thread(fetch_recent, DATABASE_PATH, HISTORY_SYMBOL)
    async def refresh():
        while True:
            await asyncio.sleep(60)
            from backend.yahoo_history import market_status
            if market_status()['status'] == 'open':
                await asyncio.to_thread(fetch_recent, DATABASE_PATH, HISTORY_SYMBOL)
    history_refresh_task = asyncio.create_task(refresh())


def load_candles() -> list[dict[str, Any]]:
    return [record.candle for record in load_minute_records(CANDLE_FILE)]


def history_result(timeframe: Timeframe, as_of: datetime | None = None) -> dict[str, Any]:
    if not os.getenv('MARKET_CANDLE_FILE'):
        return recorded_history(DATABASE_PATH, HISTORY_SYMBOL, timeframe, as_of)
    return aggregate_timeframe(
        load_minute_records(CANDLE_FILE),
        timeframe=timeframe,
        as_of=as_of,
    )


def indicator_instances(symbol: str, timeframe: Timeframe) -> list[dict[str, Any]]:
    result = history_result(timeframe)
    return [
        instance_with_values(instance, result["candles"], result["status"])
        for instance in indicator_store.list(symbol, timeframe)
    ]


def paper_snapshot(symbol: str) -> dict[str, Any]:
    return {
        **paper_account.snapshot(symbol),
        "fixture_enabled": PAPER_FIXTURE_ENABLED,
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "backend"}


@app.post("/api/decision-snapshots", status_code=201)
def create_decision_snapshot(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return decision_store.create_snapshot(
            symbol=str(payload.get("symbol", "")),
            timeframe=str(payload.get("timeframe", "")),
            cutoff=str(payload.get("cutoff", "")),
            candles=payload.get("candles"),
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/decisions", status_code=201)
def create_decision(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    snapshot_id = str(payload.get("snapshot_id", "")).strip()
    try:
        snapshot = decision_store.get_snapshot(snapshot_id)
        for request_key, snapshot_key in (
            ("symbol", "symbol"),
            ("timeframe", "interval"),
            ("cutoff", "cutoff"),
        ):
            if str(payload.get(request_key, "")) != str(snapshot[snapshot_key]):
                raise ValueError(
                    "The chart metadata does not match the saved snapshot; recapture the chart."
                )
        image = decode_png(payload.get("image_data_url"))
        provider, base_url, api_key = provider_settings()
        timeout = float(os.getenv("DECISION_TIMEOUT_SECONDS", "30"))
        request_body = decision_request(snapshot, payload["image_data_url"])
        analyst_error = None
        reviewer_error = None
        analyst_response: dict[str, Any] = {}
        reviewer_response: dict[str, Any] = {}
        try:
            analyst_response = call_decision_provider(
                request_body, url=base_url, api_key=api_key, timeout=timeout,
            )
        except ValueError as error:
            analyst_error = str(error)
        if not isinstance(analyst_response, dict):
            analyst_response = {}
            analyst_error = "Analyst returned an invalid response object."
        answers, analyst_valid, reasons = validate_answers(analyst_response, snapshot)
        if analyst_error:
            reasons.append(f"Analyst call failed: {analyst_error}")
        reviewer_answers: list[dict[str, Any]] = []
        if analyst_valid and not analyst_error:
            reviewer_body = review_request(snapshot, payload["image_data_url"], answers)
            try:
                reviewer_response = call_decision_provider(
                    reviewer_body, url=base_url, api_key=api_key, timeout=timeout,
                )
            except ValueError as error:
                reviewer_error = str(error)
            if not isinstance(reviewer_response, dict):
                reviewer_response = {}
                reviewer_error = "Reviewer returned an invalid response object."
            reviewer_answers, invalid_review = validate_review(reviewer_response)
            if reviewer_error:
                reasons.append(f"Reviewer call failed: {reviewer_error}")
            if invalid_review:
                reasons.append(invalid_review)
        else:
            reasons.append("Reviewer skipped because the analyst reply was invalid.")
        final_check, rule_reasons = final_rule_check(snapshot, answers, reviewer_answers)
        reasons.extend(rule_reasons)
        current_order_count = len(paper_account.snapshot(snapshot["symbol"])["orders"])
        orders_unchanged = (
            current_order_count == snapshot["paper_position"]["order_count"]
        )
        if not orders_unchanged:
            reasons.append("Paper orders changed while analysis was running.")
        eligible = not reasons
        return decision_store.save_decision(
            snapshot=snapshot,
            image=image,
            provider=provider,
            model=str(analyst_response.get("model", request_body["model"])),
            answers=answers,
            eligible=eligible,
            reasons=reasons,
            paper_orders_unchanged=orders_unchanged,
            reviewer_model=(str(reviewer_response.get("model", "gpt-6-luna"))
                            if reviewer_response else None),
            reviewer_answers=reviewer_answers,
            final_check=final_check,
            analyst_error=analyst_error,
            reviewer_error=reviewer_error,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/decisions/{decision_id}/capture")
def decision_capture(decision_id: str) -> FileResponse:
    try:
        path = decision_store.decision_capture(decision_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Decision capture not found") from error
    return FileResponse(path, media_type="image/png", filename=path.name)


@app.get("/api/saved-decisions")
def saved_decisions(symbol: str = Query(HISTORY_SYMBOL, min_length=1)) -> list[dict[str, Any]]:
    return list_decision_summaries(DATABASE_PATH, symbol.upper())


@app.post("/api/voice-sessions", status_code=201)
def start_voice_session(payload: dict[str, Any] = Body(...)) -> dict[str, str]:
    decision_id = payload.get("decision_id")
    if not isinstance(decision_id, str) or not decision_id.startswith("dec_"):
        raise HTTPException(status_code=422, detail="Select a saved decision before starting voice.")
    try:
        summary = decision_summary(DATABASE_PATH, decision_id)
        return create_live_session(payload.get("offer_sdp"), summary)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Selected decision was not found.") from error
    except ValueError as error:
        message = str(error)
        status = (503 if message.startswith("OPENAI_API_KEY") else
                  502 if "provider" in message.lower() else 422)
        raise HTTPException(status_code=status, detail=message) from error


@app.get("/api/paper-account")
def get_paper_account(
    symbol: str = Query(HISTORY_SYMBOL, min_length=1),
) -> dict[str, Any]:
    return paper_snapshot(symbol)


@app.get("/api/paper-automation")
def get_paper_automation(symbol: str = HISTORY_SYMBOL, timeframe: str = "1m") -> dict[str, Any]:
    return paper_account.automation_status(symbol, timeframe)


@app.post("/api/paper-automation")
def set_paper_automation(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        if not isinstance(payload.get("enabled"), bool):
            raise ValueError("enabled must be true or false")
        if payload["enabled"] and PAPER_FIXTURE_ENABLED and DATABASE_PATH == DEFAULT_DATABASE.resolve():
            raise ValueError("Test automation requires a separate disposable MARKET_DATABASE.")
        if payload["enabled"] and not LIVE_FEED_ENABLED and not PAPER_FIXTURE_ENABLED:
            raise ValueError("Offline synthetic automation requires a disposable fixture account.")
        return paper_account.set_automation(
            symbol=str(payload.get("symbol", HISTORY_SYMBOL)),
            interval=str(payload.get("timeframe", "1m")),
            enabled=payload["enabled"], order_size=payload.get("order_size", 1),
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/paper-automation/execute")
def execute_automation_decision(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        event = paper_account.submit_automation_decision(
            decision_id=str(payload.get("decision_id", "")),
            symbol=str(payload.get("symbol", "")),
            interval=str(payload.get("timeframe", "")),
            candle=str(payload.get("cutoff", "")),
            generation=int(payload.get("generation", -1)),
        )
        return {"event": event, "account": paper_snapshot(event.get("symbol", HISTORY_SYMBOL))}
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/paper-automation/claim")
def claim_automation_candle(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return paper_account.claim_automation_candle(
            symbol=str(payload.get("symbol", "")), interval=str(payload.get("timeframe", "")),
            candle=str(payload.get("cutoff", "")), generation=int(payload.get("generation", -1)),
        )
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/paper-automation/skip")
def skip_automation_analysis(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    event = paper_account.record_automation_skip(
        symbol=str(payload.get("symbol", "")), interval=str(payload.get("timeframe", "")),
        candle=str(payload.get("cutoff", "")),
        reason=str(payload.get("reason", "Chart or image was unavailable."))[:500],
        generation=int(payload.get("generation", -1)),
    )
    return {"event": event}


@app.post("/api/paper-orders")
def submit_paper_order(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    symbol = str(payload.get("symbol", HISTORY_SYMBOL)).strip().upper()
    try:
        result = execute_paper_action(
            paper_account,
            request_id=str(payload.get("request_id", "")),
            symbol=symbol,
            action=str(payload.get("action", "")),
            quantity=payload.get("quantity"),
            submitted_at=datetime.now(timezone.utc),
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"result": result, "account": paper_snapshot(symbol)}


@app.post("/api/paper-fixture-price")
def supply_paper_fixture_price(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    if not PAPER_FIXTURE_ENABLED:
        raise HTTPException(status_code=404, detail="Paper fixture input is disabled")
    symbol = str(payload.get("symbol", HISTORY_SYMBOL)).strip().upper()
    price = payload.get("price")
    receipt_time = datetime.now(timezone.utc)
    message = {
        "id": symbol,
        "time": int(receipt_time.timestamp() * 1000),
        "price": price,
        "test_data": True,
        "test_data_label": "TEST DATA — paper account browser fixture",
    }
    try:
        with MarketRecorder(DATABASE_PATH) as recorder:
            storage = recorder.record_message(message, receipt_time, ticker=symbol)
        processed = paper_account.process_market_observation(
            symbol=symbol,
            price=price,
            observation_id=storage.observation_id,
            receipt_id=storage.receipt_id,
            arrival_time=receipt_time,
            source=message["test_data_label"],
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "source": message["test_data_label"],
        "storage": storage.to_dict(),
        "processed_orders": processed,
        "account": paper_snapshot(symbol),
    }


@app.post("/api/paper-fixture-valuation")
def supply_paper_fixture_valuation(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    if not PAPER_FIXTURE_ENABLED:
        raise HTTPException(status_code=404, detail="Paper fixture input is disabled")
    symbol = str(payload.get("symbol", HISTORY_SYMBOL)).strip().upper()
    price = payload.get("price")
    event_key = str(payload.get("event_key", "")).strip()
    if not event_key:
        raise HTTPException(status_code=422, detail="event_key is required")
    receipt_time = datetime.now(timezone.utc)
    source = "TEST DATA — completed candle valuation fixture"
    message = {
        "id": symbol,
        "time": int(receipt_time.timestamp() * 1000),
        "price": price,
        "test_data": True,
        "test_data_label": source,
    }
    try:
        with MarketRecorder(DATABASE_PATH) as recorder:
            storage = recorder.record_message(message, receipt_time, ticker=symbol)
        row = paper_account.record_completed_candle_valuation(
            event_key=event_key,
            symbol=symbol,
            price=price,
            event_time=receipt_time,
            source=source,
            observation_id=storage.observation_id,
            receipt_id=storage.receipt_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "source": source,
        "storage": storage.to_dict(),
        "pnl_row": row,
        "account": paper_snapshot(symbol),
    }


@app.get("/api/replay/selections")
def replay_selections() -> dict[str, Any]:
    return {
        "mode": "Replay",
        "read_only": True,
        "live_feed_enabled": LIVE_FEED_ENABLED,
        "selections": replay_reader.selections(),
    }


@app.get("/api/indicator-types")
def available_indicator_types() -> dict[str, Any]:
    return indicator_type_contracts()


@app.get("/api/indicators")
def list_indicators(
    symbol: str = Query(HISTORY_SYMBOL, min_length=1),
    timeframe: Timeframe = "1m",
) -> dict[str, Any]:
    normalized_symbol = symbol.strip().upper()
    if normalized_symbol != HISTORY_SYMBOL:
        raise HTTPException(status_code=404, detail="Unknown chart symbol")
    return {
        "symbol": normalized_symbol,
        "timeframe": timeframe,
        "instances": indicator_instances(normalized_symbol, timeframe),
    }


@app.post("/api/indicators", status_code=201)
def create_indicator(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    symbol = str(payload.get("symbol", HISTORY_SYMBOL)).strip().upper()
    timeframe = str(payload.get("timeframe", "1m"))
    indicator_type = str(payload.get("type", "")).strip().lower()
    if symbol != HISTORY_SYMBOL:
        raise HTTPException(status_code=404, detail="Unknown chart symbol")
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise HTTPException(status_code=422, detail="Unsupported timeframe")
    if indicator_type not in INDICATOR_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown indicator type: {indicator_type or '(missing)' }.",
        )
    try:
        indicator_store.create(
            symbol,
            timeframe,
            payload.get("name", ""),
            indicator_type,
            payload.get("settings"),
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    instances = indicator_instances(symbol, timeframe)
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "instances": instances,
        "created": instances[-1],
    }


@app.put("/api/indicators/{indicator_id}")
def update_indicator(indicator_id: int, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        current = indicator_store.get(indicator_id)
        indicator_store.update_settings(indicator_id, payload.get("settings"))
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Indicator not found") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"instances": indicator_instances(current.symbol, current.timeframe)}


@app.post("/api/indicators/evaluate")
def evaluate_indicators(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    symbol = str(payload.get("symbol", "")).strip().upper()
    timeframe = str(payload.get("timeframe", ""))
    candles = payload.get("candles")
    status = payload.get("status")
    if symbol != HISTORY_SYMBOL or timeframe not in SUPPORTED_TIMEFRAMES:
        raise HTTPException(status_code=422, detail="Unsupported replay chart")
    if not isinstance(candles, list) or not isinstance(status, list):
        raise HTTPException(status_code=422, detail="Replay candles and status must be arrays")
    if len(candles) > 10000 or len(status) > 10000:
        raise HTTPException(status_code=422, detail="Replay selection is too large")
    try:
        instances = [instance_with_values(instance, candles, status)
                     for instance in indicator_store.list(symbol, timeframe)]
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=f"Invalid replay candles: {error}") from error
    return {"symbol": symbol, "timeframe": timeframe, "instances": instances}


@app.get("/api/history")
def history(
    symbol: str = Query(HISTORY_SYMBOL, min_length=1),
    timeframe: Timeframe = "1m",
    as_of: datetime | None = None,
) -> dict[str, Any]:
    normalized_symbol = symbol.strip().upper()
    if normalized_symbol != HISTORY_SYMBOL:
        raise HTTPException(
            status_code=404,
            detail=f"No local candle history is available for {normalized_symbol}",
        )
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise HTTPException(status_code=422, detail="Unsupported timeframe")
    if as_of is not None and as_of.tzinfo is None:
        raise HTTPException(
            status_code=422,
            detail="as_of must include a timezone, preferably UTC",
        )

    result = history_result(timeframe, as_of)
    return {
        "symbol": normalized_symbol,
        "live_feed_enabled": LIVE_FEED_ENABLED,
        **result,
    }


@app.websocket("/ws/candles")
async def candle_stream(websocket: WebSocket) -> None:
    symbol = websocket.query_params.get("symbol", HISTORY_SYMBOL).strip().upper()
    timeframe = websocket.query_params.get("timeframe", "1m")
    if not LIVE_FEED_ENABLED:
        await websocket.close(code=1013, reason="Live feed is disabled")
        return
    if symbol != HISTORY_SYMBOL or timeframe not in SUPPORTED_TIMEFRAMES:
        await websocket.close(code=1008, reason="Unsupported symbol or timeframe")
        return

    client_id = await candle_hub.add_client(websocket, symbol, timeframe)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await candle_hub.remove_client(client_id)


@app.websocket("/ws/replay")
async def replay_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    symbol = websocket.query_params.get("symbol", "").strip().upper()
    timeframe = websocket.query_params.get("timeframe", "1m")
    start_value = websocket.query_params.get("start", "")
    end_value = websocket.query_params.get("end", "")
    try:
        speed = float(websocket.query_params.get("speed", "20"))
        if timeframe not in SUPPORTED_TIMEFRAMES:
            raise ValueError("Unsupported replay timeframe")
        if not symbol:
            raise ValueError("Replay symbol is required")
        if speed <= 0 or speed > 1000:
            raise ValueError("Replay speed must be greater than 0 and at most 1000")
        start = parse_utc(start_value)
        end = parse_utc(end_value)
        if start >= end:
            raise ValueError("Replay start must be before replay end")
        result = replay_engine.replay(symbol, timeframe, start, end)
        if not result["events"]:
            await websocket.send_json(
                {
                    "type": "replay_empty",
                    "mode": "Replay",
                    "symbol": symbol,
                    "interval": timeframe,
                    "message": "This selection has no recorded observations.",
                    "stored_observation_count": result[
                        "stored_observation_count_after"
                    ],
                }
            )
            await websocket.close(code=1000)
            return

        await websocket.send_json(
            {
                "type": "replay_started",
                "mode": "Replay",
                "read_only": True,
                "symbol": symbol,
                "interval": timeframe,
                "total": len(result["events"]),
                "feed_status": "disconnected",
            }
        )
        previous_receipt: datetime | None = None
        for event in result["events"]:
            receipt_time = parse_utc(event["replay_receipt_time"])
            if previous_receipt is not None:
                delay = max(0.0, (receipt_time - previous_receipt).total_seconds())
                await asyncio.sleep(min(delay / speed, 1.0))
            event_price = event.get("market_price")
            if event_price is not None:
                paper_account.process_market_observation(
                    symbol=symbol,
                    price=event_price,
                    observation_id=event["observation_id"],
                    receipt_id=event["receipt_id"],
                    arrival_time=receipt_time,
                    source="Recorded SQLite replay",
                )
            for update in event["updates"]:
                if update["completion"]["interval_ended"]:
                    completed = update["candle"]
                    paper_account.record_completed_candle_valuation(
                        event_key=(
                            f"completed-candle:{symbol}:{timeframe}:"
                            f"{completed['timestamp']}:close-cents:"
                            f"{dollars_to_cents(completed['close'])}"
                        ),
                        symbol=symbol,
                        price=completed["close"],
                        event_time=receipt_time,
                        source=f"Recorded SQLite replay · completed {timeframe} candle",
                        observation_id=event["observation_id"],
                        receipt_id=event["receipt_id"],
                    )
            await websocket.send_json(event)
            previous_receipt = receipt_time

        await websocket.send_json(
            {
                "type": "replay_complete",
                "mode": "Replay",
                "read_only": True,
                "symbol": symbol,
                "interval": timeframe,
                "final_candles": result["final_candles"],
                "stored_observation_count_before": result[
                    "stored_observation_count_before"
                ],
                "stored_observation_count_after": result[
                    "stored_observation_count_after"
                ],
            }
        )
        await websocket.close(code=1000)
    except ValueError as error:
        await websocket.send_json(
            {
                "type": "replay_error",
                "mode": "Replay",
                "message": str(error),
            }
        )
        await websocket.close(code=1008)


@app.on_event("shutdown")
async def stop_candle_hub() -> None:
    if history_refresh_task:
        history_refresh_task.cancel()
        try:
            await history_refresh_task
        except asyncio.CancelledError:
            pass
    await candle_hub.close()
    indicator_store.close()
    decision_store.close()
    paper_account.close()
