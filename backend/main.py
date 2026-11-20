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
from backend.yahoo_history import fetch_recent, persist_download, market_status
from backend.daily_history import download as download_daily, persist as persist_daily, refresh_needed as daily_refresh_needed, oldest_page_before
from backend.interval_history import download as download_interval, persist as persist_interval, refresh_needed as interval_refresh_needed, INTERVAL_MINUTES
from backend.database import database_path, prepare_database, DatabaseOwner
from backend.write_coordinator import WriteCoordinator
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
from backend.chat_agent import run_chat
from backend.sma_engine import crossover_series
from backend.accounting import quote_entry
from backend.backtesting import settings as backtest_settings, run_backtest, digest as backtest_digest
from backend.backtest_store import BacktestStore, RequestConflict, load_dataset


DATABASE_PATH = database_path()
DATABASE_PATH.parent.mkdir(parents=True,exist_ok=True)
database_owner = DatabaseOwner(DATABASE_PATH)
prepare_database(DATABASE_PATH)
with MarketRecorder(DATABASE_PATH):
    pass
paper_account = PaperAccount(
    DATABASE_PATH,
    os.getenv("PAPER_STARTING_CASH", "10000"),
)

app = FastAPI(title="Plunderer's Port API")
writer = WriteCoordinator()
writer_loop = None


@app.middleware('http')
async def serialize_mutations(request, call_next):
    if request.method in ('POST','PUT','PATCH','DELETE') and request.url.path not in ('/api/decisions','/api/voice-sessions','/api/chat','/api/strategy-signals') and not request.url.path.startswith('/api/backtests'):
        return await writer.run(lambda:call_next(request))
    return await call_next(request)
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
recent_history_tasks = {}
recent_history_attempts = {}
daily_history_tasks = {}
interval_history_tasks = {}
backtest_store = BacktestStore(DATABASE_PATH)
backtest_lock = asyncio.Lock()


async def execute_backtest(payload, original_run=None):
    request_id = payload.get('request_id')
    if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 128:
        raise HTTPException(status_code=422, detail='A backtest request_id of 1–128 characters is required.')
    try:
        config = backtest_settings(payload) if original_run is None else backtest_store.get(original_run)['settings']
        request_hash = backtest_digest(dict(settings=config, original_run=original_run))
        previous = backtest_store.existing(request_id, request_hash)
        if previous:
            return previous
        if backtest_lock.locked():
            raise HTTPException(status_code=409, detail='Another backtest is running; retry with the same request ID.')
        async with backtest_lock:
            if original_run is None:
                config, dataset = await asyncio.to_thread(load_dataset, DATABASE_PATH, config)
            else:
                dataset = backtest_store.dataset(original_run)
            result = await asyncio.to_thread(run_backtest, config, dataset)
            return await writer.run(lambda: backtest_store.save(request_id, request_hash, dataset, result))
    except RequestConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except KeyError as error:
        raise HTTPException(status_code=404, detail='Stored backtest not found.') from error
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post('/api/backtests', status_code=201)
async def create_backtest(payload: dict[str, Any] = Body(...)):
    return await execute_backtest(payload)


@app.post('/api/backtests/{run_id}/rerun', status_code=201)
async def rerun_backtest(run_id: str, payload: dict[str, Any] = Body(...)):
    return await execute_backtest(payload, run_id)


@app.get('/api/backtests')
def list_backtests(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    return dict(runs=backtest_store.list(limit, offset), limit=limit, offset=offset)


@app.get('/api/backtests/{run_id}')
def get_backtest(run_id: str):
    try:
        return backtest_store.get(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail='Stored backtest not found.') from error


@app.get('/api/backtests/{run_id}/dataset')
def get_backtest_dataset(run_id: str):
    try:
        return backtest_store.dataset(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail='Stored backtest not found.') from error


def request_interval_history(symbol, interval):
    key = (symbol,interval)
    task = interval_history_tasks.get(key)
    if task and not task.done():
        return task
    if not interval_refresh_needed(DATABASE_PATH,symbol,interval):
        return None
    async def refresh_interval():
        result = await asyncio.to_thread(download_interval,DATABASE_PATH,symbol,interval)
        await writer.run(lambda:persist_interval(DATABASE_PATH,symbol,interval,result))
    task = asyncio.create_task(refresh_interval())
    interval_history_tasks[key] = task
    return task


def request_daily_history(symbol=HISTORY_SYMBOL):
    task = daily_history_tasks.get(symbol)
    if task and not task.done():
        return task
    if not daily_refresh_needed(DATABASE_PATH,symbol):
        return None
    async def refresh_daily():
        result = await asyncio.to_thread(download_daily,symbol)
        await writer.run(lambda:persist_daily(DATABASE_PATH,symbol,result))
    task = asyncio.create_task(refresh_daily())
    daily_history_tasks[symbol] = task
    return task


async def reconcile_recent_history(symbol=HISTORY_SYMBOL):
    """Share startup/selection downloads; network waits never occupy the SQLite writer."""
    with MarketRecorder(DATABASE_PATH) as store:
        latest = store.connection.execute('''SELECT MAX(minute_start) FROM candles_1m
            WHERE instrument_id=(SELECT instrument_id FROM instruments WHERE symbol=?)''',(symbol,)).fetchone()[0]
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    beginning = max(datetime.fromtimestamp(latest,timezone.utc)-timedelta(minutes=5),now-timedelta(days=7)+timedelta(minutes=1)) if latest else None
    result = await asyncio.to_thread(fetch_recent,DATABASE_PATH,symbol,beginning,True)
    if latest and now-datetime.fromtimestamp(latest,timezone.utc)>timedelta(days=7):
        result['message'] = 'Some older minutes may be outside Yahoo minute-history retention; gaps are preserved.'
    await writer.run(lambda:persist_download(DATABASE_PATH,symbol,result))


def request_recent_history(symbol=HISTORY_SYMBOL):
    task = recent_history_tasks.get(symbol)
    if task is None or task.done():
        task = asyncio.create_task(reconcile_recent_history(symbol))
        recent_history_tasks[symbol] = task
        recent_history_attempts[symbol] = asyncio.get_running_loop().time()
    return task


@app.on_event('startup')
async def start_history_refresh():
    global history_refresh_task, writer_loop
    writer_loop = asyncio.get_running_loop()
    # Fixtures and explicitly offline runs never contact Yahoo.
    if (not LIVE_FEED_ENABLED or os.getenv('MARKET_CANDLE_FILE')
            or os.getenv('MARKET_TEST_FEED', '0') == '1'):
        return
    await candle_hub.start(writer)
    async def refresh():
        previous = None
        close_attempts = 0
        while True:
            state = market_status()
            if previous is None or state['status']=='open' or previous=='open' or close_attempts:
                request_daily_history()
                for interval in {c.timeframe for c in candle_hub.clients.values()} & set(INTERVAL_MINUTES):
                    request_interval_history(HISTORY_SYMBOL,interval)
                await request_recent_history()
                if previous=='open' and state['status']=='closed':
                    close_attempts = 3
                elif close_attempts:
                    close_attempts -= 1
            previous = state['status']
            await asyncio.sleep(60 if state['status']=='open' or close_attempts else min(30,max(1,(datetime.fromisoformat(state['next_open'].replace('Z','+00:00'))-datetime.now(timezone.utc)).total_seconds())))
    history_refresh_task = asyncio.create_task(refresh())


def load_candles() -> list[dict[str, Any]]:
    return [record.candle for record in load_minute_records(CANDLE_FILE)]


def history_result(timeframe: Timeframe, as_of: datetime | None = None, limit=2000, before=None, start=None) -> dict[str, Any]:
    if not os.getenv('MARKET_CANDLE_FILE'):
        if candle_hub.manual_test and as_of is None:
            as_of = candle_hub._now()
        apply_policy = not candle_hub.manual_test and not candle_hub.test_feed
        result = recorded_history(DATABASE_PATH, HISTORY_SYMBOL, timeframe, as_of,min(limit,2000),before,start,apply_policy=apply_policy)
        # Indicator/snapshot warm-up is bounded by validated settings, independent of browser paging.
        while len(result['candles'])<limit and result['next_before']:
            cursor = result['next_before']
            older = recorded_history(DATABASE_PATH,HISTORY_SYMBOL,timeframe,as_of,min(limit-len(result['candles']),2000),cursor,start,apply_policy=apply_policy)
            result['candles'] = older['candles']+result['candles']
            result['status'] = older['status']+result['status']
            result['next_before'] = older['next_before']
            if not older['candles'] or older['next_before']==cursor:
                break
        return result
    result = aggregate_timeframe(
        load_minute_records(CANDLE_FILE),
        timeframe=timeframe,
        as_of=as_of,
    )
    pairs = [(c,s) for c,s in zip(result['candles'],result['status'])
        if (not before or parse_utc(c['timestamp'])<parse_utc(before))
        and (not start or parse_utc(c['timestamp'])>=parse_utc(start))]
    result['next_before'] = pairs[-limit][0]['timestamp'] if len(pairs)>limit else None
    result['candles'] = [c for c,s in pairs[-limit:]]
    result['status'] = [s for c,s in pairs[-limit:]]
    return result


def indicator_instances(symbol: str, timeframe: Timeframe, before=None, limit=2000) -> list[dict[str, Any]]:
    configurations = indicator_store.list(symbol,timeframe)
    window = max((item.settings['window'] for item in configurations),default=1)
    result = history_result(timeframe,limit=min(12000,limit+window),before=before)
    visible_times = {c['timestamp'] for c in result['candles'][-limit:]}
    instances = [
        instance_with_values(instance, result["candles"], result["status"])
        for instance in configurations
    ]
    for item in instances:
        item['values'] = [point for point in item['values'] if point['timestamp'] in visible_times]
    return instances


def paper_snapshot(symbol: str) -> dict[str, Any]:
    return {
        **paper_account.snapshot(symbol),
        "fixture_enabled": PAPER_FIXTURE_ENABLED,
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "backend"}


@app.post('/api/market-fixture')
async def market_fixture(payload: dict[str, Any] = Body(...)):
    if not (PAPER_FIXTURE_ENABLED and candle_hub.manual_test and DATABASE_PATH!=DEFAULT_DATABASE):
        raise HTTPException(status_code=404,detail='Market fixture input disabled')
    receipt = parse_utc(payload['receipt_time'])
    source = parse_utc(payload['source_time'])
    message = dict(id='AAPL',time=int(source.timestamp()*1000),price=payload['price'],
        day_volume=payload.get('volume'),test_data=True,test_data_label='TEST DATA — continuous browser fixture')
    await candle_hub.publish_observation('AAPL',message,receipt,message['test_data_label'],broadcast=False)
    import time
    return {'committed_at_ms':round(time.time()*1000),'price':payload['price']}


@app.post("/api/decision-snapshots", status_code=201)
def create_decision_snapshot(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        tf = str(payload.get('timeframe','1m'))
        from datetime import timedelta
        bound = (parse_utc(str(payload.get('cutoff','')))+timedelta(minutes={'1m':1,'5m':5,'15m':15,'1h':60,'1d':1440}[tf])).isoformat()
        context = history_result(tf,limit=12000,before=bound)
        return decision_store.create_snapshot(
            symbol=str(payload.get("symbol", "")),
            timeframe=str(payload.get("timeframe", "")),
            cutoff=str(payload.get("cutoff", "")),
            candles=payload.get("candles"),
            context=context,
            fast_id=payload.get('fast_id'), slow_id=payload.get('slow_id'),
        )
    except (ValueError,KeyError) as error:
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
        # Provider calls ran outside the write queue. Persist only the result in FIFO order.
        def save():
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
        return asyncio.run_coroutine_threadsafe(writer.run(save),writer_loop).result()
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


@app.post("/api/chat")
async def workstation_chat(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    message = str(payload.get("message", "")).strip()
    if not message or len(message) > 2000:
        raise HTTPException(status_code=422, detail="Enter a chat message between 1 and 2,000 characters.")
    chart = payload.get("chart")
    if chart is not None:
        if not isinstance(chart, dict):
            raise HTTPException(status_code=422, detail="Captured chart context must be an object.")
        required = ("snapshot_id", "symbol", "timeframe", "cutoff", "image_data_url")
        if any(not isinstance(chart.get(key), str) or not chart[key] for key in required):
            raise HTTPException(status_code=422, detail="Captured chart context is incomplete; recapture it.")
        if chart.get("data_mode") not in ("live", "replay"):
            raise HTTPException(status_code=422, detail="Captured chart data mode must be live or replay.")
    try:
        return await run_chat(message, chart, create_decision, payload.get("conversation_id"))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except TimeoutError as error:
        raise HTTPException(status_code=504, detail="The assistant timed out; retry the captured-chart request.") from error
    except Exception as error:
        raise HTTPException(status_code=502, detail="The assistant service failed. Check the backend provider configuration and retry.") from error


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
        "live_feed_enabled": LIVE_FEED_ENABLED or candle_hub.manual_test,
        "selections": replay_reader.selections(),
    }


@app.get("/api/indicator-types")
def available_indicator_types() -> dict[str, Any]:
    return indicator_type_contracts()


@app.post('/api/strategy-signals')
def strategy_signals(payload: dict[str, Any] = Body(...)):
    """Read-only preview math. Live context is verified; Replay uses its supplied prefix."""
    try:
        symbol = payload.get('symbol')
        timeframe = payload.get('timeframe')
        mode = payload.get('data_mode')
        quantity = payload.get('quantity', 1)
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            raise ValueError('Strategy quantity must be a positive whole number.')
        if symbol != HISTORY_SYMBOL or timeframe not in SUPPORTED_TIMEFRAMES or mode not in ('live', 'replay'):
            raise ValueError('Unsupported strategy chart context.')
        fast = indicator_store.get(int(payload['fast_id']))
        slow = indicator_store.get(int(payload['slow_id']))
        if any(item.symbol != symbol or item.timeframe != timeframe or item.indicator_type != 'sma' for item in (fast, slow)):
            raise ValueError('Select two saved SMAs for this chart.')
        if fast.settings['window'] >= slow.settings['window']:
            raise ValueError('Fast SMA length must be smaller than slow SMA length.')
        candles, status = payload['candles'], payload['status']
        if not isinstance(candles, list) or not 1 <= len(candles) <= 6000 or not isinstance(status, list):
            raise ValueError('Strategy context must contain 1–6000 candles and completion flags.')
        visible = {item['timestamp'] for item in candles}
        prices = {item['timestamp']: item['close'] for item in candles}
        if len(status) > 6000 or {item['timestamp'] for item in status} != visible:
            raise ValueError('Completion flags must match the supplied chart prefix.')
        if any(not isinstance(item.get('interval_ended'), bool) or not isinstance(item.get('coverage_complete'), bool) for item in status):
            raise ValueError('Chart completion and coverage flags must be explicit booleans.')
        client_flags = {item['timestamp']: item for item in status}
        # UTC parsing rejects malformed/naive timestamps before any history read.
        for candle in candles:
            parse_utc(candle['timestamp'])
        if mode == 'live':
            from datetime import timedelta
            end = (parse_utc(candles[-1]['timestamp']) + timedelta(minutes={'1m':1,'5m':5,'15m':15,'1h':60,'1d':1440}[timeframe])).isoformat()
            context = history_result(timeframe, limit=min(16000, len(candles) + slow.settings['window'] + 1), before=end)
            known = {item['timestamp']: item for item in context['candles']}
            if any(known.get(item['timestamp']) != item for item in candles):
                raise HTTPException(status_code=409, detail='Chart changed before signal calculation; wait for the next chart refresh.')
            candles, status = context['candles'], context['status']
            # Never promote a still-forming/partial chart view ahead of its socket update.
            status = [{**item, 'interval_ended': False}
                      if item['timestamp'] in client_flags and not (
                          client_flags[item['timestamp']]['interval_ended'] and client_flags[item['timestamp']]['coverage_complete'])
                      else item for item in status]
        first = instance_with_values(fast, candles, status)
        second = instance_with_values(slow, candles, status)
        points = crossover_series(first['values'], second['values'])
        quoted = [{**point, **quote_entry(prices[point['timestamp']], quantity)} for point in points if point['timestamp'] in visible]
        if any(point['estimated_cost_cents'] > 9007199254740991 for point in quoted):
            raise ValueError('The requested entry estimate exceeds the browser exact-integer limit.')
        return dict(fast_id=fast.indicator_id, slow_id=slow.indicator_id, symbol=symbol, quantity=quantity,
                    timeframe=timeframe, data_mode=mode,
                    points=quoted)
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/indicators")
def list_indicators(
    symbol: str = Query(HISTORY_SYMBOL, min_length=1),
    timeframe: Timeframe = "1m",
    before: datetime | None = None,
    limit: int = Query(2000,ge=1,le=2000),
) -> dict[str, Any]:
    normalized_symbol = symbol.strip().upper()
    if before is not None and before.tzinfo is None:
        raise HTTPException(status_code=422,detail='before must include a timezone')
    if normalized_symbol != HISTORY_SYMBOL:
        raise HTTPException(status_code=404, detail="Unknown chart symbol")
    return {
        "symbol": normalized_symbol,
        "timeframe": timeframe,
        "instances": indicator_instances(normalized_symbol, timeframe,before.isoformat() if before else None,limit),
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
async def history(
    symbol: str = Query(HISTORY_SYMBOL, min_length=1),
    timeframe: Timeframe = "1m",
    as_of: datetime | None = None,
    limit: int = Query(2000,ge=1,le=2000),
    before: datetime | None = None,
    start: datetime | None = None,
    recent: bool = False,
    oldest: bool = False,
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

    for bound in (before,start):
        if bound is not None and bound.tzinfo is None:
            raise HTTPException(status_code=422,detail='History bounds must include a timezone')
    if oldest and (before is not None or start is not None or as_of is not None):
        raise HTTPException(status_code=422,detail='oldest cannot be combined with other history bounds')
    interval_task = None
    if (timeframe in INTERVAL_MINUTES and recent and as_of is None and LIVE_FEED_ENABLED
            and not os.getenv('MARKET_CANDLE_FILE') and not candle_hub.test_feed and not candle_hub.manual_test):
        interval_task = request_interval_history(normalized_symbol,timeframe)
    daily_task = None
    if (timeframe=='1d' and recent and as_of is None and LIVE_FEED_ENABLED
            and not os.getenv('MARKET_CANDLE_FILE') and not candle_hub.test_feed and not candle_hub.manual_test):
        daily_task = request_daily_history(normalized_symbol)
    before_value = before.isoformat() if before else None
    if oldest:
        if timeframe=='1d':
            before_value = oldest_page_before(DATABASE_PATH,normalized_symbol,limit)
        else:
            window = recorded_history(DATABASE_PATH,normalized_symbol,timeframe,limit=5000,apply_policy=True)
            before_value = window['candles'][limit]['timestamp'] if len(window['candles'])>limit else None
    result = await asyncio.to_thread(history_result,timeframe,as_of,limit,before_value,start.isoformat() if start else None)
    # Opening a company must not depend on an open exchange or a new WebSocket tick.
    if (recent and as_of is None and before is None and start is None and LIVE_FEED_ENABLED
            and not os.getenv('MARKET_CANDLE_FILE') and not candle_hub.test_feed and not candle_hub.manual_test):
        elapsed = asyncio.get_running_loop().time()-recent_history_attempts.get(normalized_symbol,float('-inf'))
        if elapsed >= 60 or (recent_history_tasks.get(normalized_symbol) and not recent_history_tasks[normalized_symbol].done()):
            task = request_recent_history(normalized_symbol)
        if not result['candles']:
            result['message'] = 'Recent Yahoo history is unavailable or still loading. Retry to load the last trading session.'
    return {
        "symbol": normalized_symbol,
        "live_feed_enabled": LIVE_FEED_ENABLED or candle_hub.manual_test,
        "daily_download_pending":bool(daily_task and not daily_task.done()),
        "interval_download_pending":bool(interval_task and not interval_task.done()),
        "minute_download_pending":bool(recent_history_tasks.get(normalized_symbol) and not recent_history_tasks[normalized_symbol].done()),
        "stream_id":candle_hub.stream_id,
        **result,
    }


@app.websocket("/ws/candles")
async def candle_stream(websocket: WebSocket) -> None:
    symbol = websocket.query_params.get("symbol", HISTORY_SYMBOL).strip().upper()
    timeframe = websocket.query_params.get("timeframe", "1m")
    if not LIVE_FEED_ENABLED and not candle_hub.manual_test:
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
                await writer.run(lambda:paper_account.process_market_observation(
                    symbol=symbol,
                    price=event_price,
                    observation_id=event["observation_id"],
                    receipt_id=event["receipt_id"],
                    arrival_time=receipt_time,
                    source="Recorded SQLite replay",
                ))
            for update in event["updates"]:
                if update["completion"]["interval_ended"]:
                    completed = update["candle"]
                    await writer.run(lambda:paper_account.record_completed_candle_valuation(
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
                    ))
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
    await asyncio.gather(*recent_history_tasks.values(),return_exceptions=True)
    await asyncio.gather(*daily_history_tasks.values(),return_exceptions=True)
    await asyncio.gather(*interval_history_tasks.values(),return_exceptions=True)
    await candle_hub.close()
    await writer.close()
    indicator_store.close()
    decision_store.close()
    backtest_store.close()
    paper_account.close()
    database_owner.close()
