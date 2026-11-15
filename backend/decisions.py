from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import struct
from threading import RLock
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from backend.indicators import IndicatorStore, instance_with_values
from backend.paper_trading import PaperAccount
from backend.timeframe_history import CANDLE_FIELDS, SUPPORTED_TIMEFRAMES


DECISION_SCHEMA = """
CREATE TABLE IF NOT EXISTS decision_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    cutoff_utc TEXT NOT NULL,
    chart_start_utc TEXT NOT NULL,
    chart_end_utc TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decision_records (
    decision_id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL REFERENCES decision_snapshots(snapshot_id),
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    image_path TEXT NOT NULL,
    image_sha256 TEXT NOT NULL,
    questions_json TEXT NOT NULL,
    answers_json TEXT NOT NULL,
    request_summary_json TEXT NOT NULL,
    eligible_for_automation INTEGER NOT NULL CHECK (eligible_for_automation IN (0, 1)),
    eligibility_reasons_json TEXT NOT NULL,
    reviewer_model TEXT,
    reviewer_answers_json TEXT,
    review_questions_json TEXT,
    final_check_json TEXT,
    analyst_error TEXT,
    reviewer_error TEXT,
    created_at_utc TEXT NOT NULL
);
"""

QUESTIONS = [
    {
        "type": "choice",
        "name": "action",
        "instructions": (
            "Which action fits this paper position and the strategy rules? "
            "Buy adds shares, sell reduces the position, hold keeps an open "
            "position, wait stays flat, and close exits the entire position."
        ),
        "choices": [
            {"value": "buy", "description": "Add whole shares."},
            {"value": "sell", "description": "Reduce an open long position."},
            {"value": "hold", "description": "Keep an open position unchanged."},
            {"value": "wait", "description": "Stay flat with no position."},
            {"value": "close", "description": "Exit the entire open position."},
        ],
    },
    {
        "type": "choice",
        "name": "crossover",
        "instructions": (
            "At the selected candle, is an upward crossover, a downward "
            "crossover, or no crossover visible? Choose unreadable if the image "
            "cannot be assessed."
        ),
        "choices": [
            {"value": "upward", "description": "Fast SMA crossed above slow SMA."},
            {"value": "downward", "description": "Fast SMA crossed below slow SMA."},
            {"value": "none", "description": "No crossover is visible at the cutoff."},
            {"value": "unreadable", "description": "The chart cannot be read reliably."},
        ],
    },
    {
        "type": "choice",
        "name": "evidence",
        "instructions": "Is the visible chart sufficient to assess the signal at the cutoff?",
        "choices": [
            {"value": "sufficient", "description": "The visible chart is sufficient."},
            {"value": "insufficient", "description": "More visible history or detail is needed."},
            {"value": "unreadable", "description": "The image cannot be read."},
        ],
    },
]

REVIEW_QUESTIONS = [{
    "type": "choice",
    "name": "verdict",
    "instructions": (
        "Review the analyst's actual action and chart answers against the frozen "
        "snapshot and backend facts. Accept only when the image supports the "
        "signal, the action follows the simple SMA strategy, and the paper "
        "account can support at least one share when buying."
    ),
    "choices": [
        {"value": "accept", "description": "Proposal is supported."},
        {"value": "reject_insufficient_cash", "description": "Cannot afford one share."},
        {"value": "reject_unsupported_signal", "description": "Signal or action is unsupported."},
        {"value": "reject_insufficient_evidence", "description": "Chart evidence is inadequate."},
        {"value": "reject_other", "description": "Another issue prevents acceptance."},
    ],
}]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _validate_candles(candles: Any, cutoff: str) -> list[dict[str, Any]]:
    if not isinstance(candles, list) or not candles:
        raise ValueError("The chart snapshot has no candles; recapture a completed chart.")
    normalized = []
    previous = ""
    for candle in candles:
        if not isinstance(candle, dict) or set(candle) != set(CANDLE_FIELDS):
            raise ValueError("Each captured candle must have exactly the six candle fields.")
        timestamp = str(candle["timestamp"])
        if timestamp <= previous:
            raise ValueError("Captured candles must be strictly ordered by timestamp.")
        if timestamp > cutoff:
            raise ValueError("The captured chart includes data after its cutoff; recapture it.")
        for field in ("open", "high", "low", "close"):
            if isinstance(candle[field], bool) or not isinstance(candle[field], (int, float)):
                raise ValueError(f"Captured candle {field} must be numeric.")
        if candle["volume"] is not None and (
            isinstance(candle["volume"], bool)
            or not isinstance(candle["volume"], (int, float))
        ):
            raise ValueError("Captured candle volume must be numeric or unknown.")
        normalized.append({field: candle[field] for field in CANDLE_FIELDS})
        previous = timestamp
    if normalized[-1]["timestamp"] != cutoff:
        raise ValueError("The chart cutoff does not match its last candle; recapture it.")
    return normalized


def calculate_crossover(indicators: list[dict[str, Any]], cutoff: str) -> dict[str, Any]:
    sma = sorted(
        (item for item in indicators if item["type"] == "sma"),
        key=lambda item: (item["settings"]["window"], item["indicator_id"]),
    )
    if len(sma) < 2:
        return {
            "signal": "none",
            "available": False,
            "reason": "Two SMA instances with different windows are required.",
        }
    fast, slow = sma[0], sma[-1]
    if fast["settings"]["window"] == slow["settings"]["window"]:
        return {
            "signal": "none",
            "available": False,
            "reason": "The fast and slow SMA windows must differ.",
        }
    fast_values = {point["timestamp"]: point["value"] for point in fast["values"]}
    slow_values = {point["timestamp"]: point["value"] for point in slow["values"]}
    usable_times = [
        timestamp
        for timestamp in fast_values
        if timestamp <= cutoff
        and fast_values[timestamp] is not None
        and slow_values.get(timestamp) is not None
    ]
    if len(usable_times) < 2:
        return {
            "signal": "none",
            "available": False,
            "reason": "The selected cutoff does not have two comparable SMA values.",
            "fast": fast["name"],
            "slow": slow["name"],
        }
    previous_time, current_time = usable_times[-2:]
    previous_delta = fast_values[previous_time] - slow_values[previous_time]
    current_delta = fast_values[current_time] - slow_values[current_time]
    signal = "none"
    if previous_delta <= 0 < current_delta:
        signal = "upward"
    elif previous_delta >= 0 > current_delta:
        signal = "downward"
    return {
        "signal": signal,
        "available": True,
        "fast": fast["name"],
        "slow": slow["name"],
        "previous": {
            "timestamp": previous_time,
            "fast": fast_values[previous_time],
            "slow": slow_values[previous_time],
        },
        "current": {
            "timestamp": current_time,
            "fast": fast_values[current_time],
            "slow": slow_values[current_time],
        },
    }


@dataclass(frozen=True)
class PngImage:
    content: bytes
    width: int
    height: int
    sha256: str


def decode_png(data_url: Any) -> PngImage:
    if not isinstance(data_url, str) or not data_url.startswith("data:image/png;base64,"):
        raise ValueError("The chart image is not a PNG data URL; recapture the chart.")
    try:
        content = base64.b64decode(data_url.split(",", 1)[1], validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("The chart PNG cannot be decoded; recapture the chart.") from error
    if len(content) < 24 or content[:8] != b"\x89PNG\r\n\x1a\n" or content[12:16] != b"IHDR":
        raise ValueError("The chart image is not a readable PNG; recapture the chart.")
    width, height = struct.unpack(">II", content[16:24])
    if width < 320 or height < 200:
        raise ValueError("The chart PNG is too small to read; recapture it at normal size.")
    return PngImage(content, width, height, hashlib.sha256(content).hexdigest())


class DecisionStore:
    def __init__(
        self,
        database_path: str | Path,
        indicator_store: IndicatorStore,
        paper_account: PaperAccount,
        capture_directory: str | Path,
    ):
        self.path = Path(database_path).expanduser().resolve()
        self.indicator_store = indicator_store
        self.paper_account = paper_account
        self.capture_directory = Path(capture_directory).expanduser().resolve()
        self.capture_directory.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(DECISION_SCHEMA)
        existing = {row[1] for row in self.connection.execute("PRAGMA table_info(decision_records)")}
        for column in ("reviewer_model", "reviewer_answers_json", "review_questions_json", "final_check_json", "analyst_error", "reviewer_error"):
            if column not in existing:
                self.connection.execute(f"ALTER TABLE decision_records ADD COLUMN {column} TEXT")
        self._lock = RLock()

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    def create_snapshot(
        self,
        symbol: str,
        timeframe: str,
        cutoff: str,
        candles: Any,
        context: dict | None = None,
    ) -> dict[str, Any]:
        normalized_symbol = str(symbol).strip().upper()
        if not normalized_symbol:
            raise ValueError("Snapshot symbol is required.")
        if timeframe not in SUPPORTED_TIMEFRAMES:
            raise ValueError("Snapshot timeframe is unsupported.")
        normalized_candles = _validate_candles(candles, cutoff)
        if context is not None:
            matching = {c['timestamp']: c for c in context['candles']}
            if any(matching.get(c['timestamp']) != c for c in normalized_candles):
                raise ValueError('Chart candles changed or are unavailable in stored history; reload and recapture the chart.')
        status = [
            {"timestamp": candle["timestamp"], "interval_ended": True}
            for candle in normalized_candles
        ]
        calculation_candles = [c for c in context['candles'] if c['timestamp']<=cutoff] if context else normalized_candles
        calculation_status = context['status'] if context else status
        indicators = [
            instance_with_values(instance, calculation_candles, calculation_status)
            for instance in self.indicator_store.list(normalized_symbol, timeframe)
        ]
        paper = self.paper_account.snapshot(normalized_symbol)
        snapshot_id = f"snap_{uuid4().hex}"
        snapshot = {
            "snapshot_id": snapshot_id,
            "symbol": normalized_symbol,
            "interval": timeframe,
            "cutoff": cutoff,
            "chart_range": {
                "start": normalized_candles[0]["timestamp"],
                "end": normalized_candles[-1]["timestamp"],
                "candles": len(normalized_candles),
            },
            "candles": normalized_candles,
            "indicators": indicators,
            "paper_position": {
                "account_id": paper["account_id"],
                "shares": paper["shares"],
                "average_cost": paper["average_cost"],
                "cash": paper["cash"],
                "order_count": len(paper["orders"]),
            },
        }
        snapshot["python_crossover"] = calculate_crossover(indicators, cutoff)
        visible = {c['timestamp'] for c in normalized_candles}
        for item in indicators:
            item['values'] = [point for point in item['values'] if point['timestamp'] in visible]
        created_at = utc_now()
        with self._lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO decision_snapshots (
                    snapshot_id, symbol, timeframe, cutoff_utc, chart_start_utc,
                    chart_end_utc, snapshot_json, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    normalized_symbol,
                    timeframe,
                    cutoff,
                    snapshot["chart_range"]["start"],
                    snapshot["chart_range"]["end"],
                    _canonical(snapshot),
                    created_at,
                ),
            )
        return snapshot

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        with self._lock:
            row = self.connection.execute(
                "SELECT snapshot_json FROM decision_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
        if row is None:
            raise ValueError("The decision snapshot was not found; recapture the chart.")
        return json.loads(row["snapshot_json"])

    def save_decision(
        self,
        *,
        snapshot: dict[str, Any],
        image: PngImage,
        provider: str,
        model: str,
        answers: list[dict[str, Any]],
        eligible: bool,
        reasons: list[str],
        paper_orders_unchanged: bool,
        reviewer_model: str | None = None,
        reviewer_answers: list[dict[str, Any]] | None = None,
        final_check: dict[str, Any] | None = None,
        analyst_error: str | None = None,
        reviewer_error: str | None = None,
    ) -> dict[str, Any]:
        decision_id = f"dec_{uuid4().hex}"
        image_path = self.capture_directory / f"{snapshot['snapshot_id']}.png"
        if image_path.exists():
            existing_sha = hashlib.sha256(image_path.read_bytes()).hexdigest()
            if existing_sha != image.sha256:
                raise ValueError("This snapshot already has a different PNG; recapture it.")
        else:
            image_path.write_bytes(image.content)
        summary = {
            "snapshot_id": snapshot["snapshot_id"],
            "image": {
                "mime_type": "image/png",
                "width": image.width,
                "height": image.height,
                "sha256": image.sha256,
            },
            "input_parts": ["input_text", "input_image", "input_json"],
        }
        created_at = utc_now()
        with self._lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO decision_records (
                    decision_id, snapshot_id, provider, model, image_path,
                    image_sha256, questions_json, answers_json,
                    request_summary_json, eligible_for_automation,
                    eligibility_reasons_json, reviewer_model, reviewer_answers_json,
                    review_questions_json, final_check_json, analyst_error,
                    reviewer_error, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    snapshot["snapshot_id"],
                    provider,
                    model,
                    str(image_path),
                    image.sha256,
                    _canonical(QUESTIONS),
                    _canonical(answers),
                    _canonical(summary),
                    int(eligible),
                    _canonical(reasons),
                    reviewer_model,
                    _canonical(reviewer_answers or []),
                    _canonical(REVIEW_QUESTIONS),
                    _canonical(final_check or {}),
                    analyst_error,
                    reviewer_error,
                    created_at,
                ),
            )
        return {
            "decision_id": decision_id,
            "snapshot": snapshot,
            "questions": QUESTIONS,
            "answers": answers,
            "provider": provider,
            "model": model,
            "image": summary["image"],
            "capture_url": f"/api/decisions/{decision_id}/capture",
            "eligible_for_automation": eligible,
            "eligibility_reasons": reasons,
            "paper_orders_unchanged": paper_orders_unchanged,
            "reviewer_model": reviewer_model,
            "review_questions": REVIEW_QUESTIONS,
            "reviewer_answers": reviewer_answers or [],
            "final_check": final_check or {},
            "analyst_error": analyst_error,
            "reviewer_error": reviewer_error,
        }

    def decision_capture(self, decision_id: str) -> Path:
        with self._lock:
            row = self.connection.execute(
                "SELECT image_path FROM decision_records WHERE decision_id = ?",
                (decision_id,),
            ).fetchone()
        if row is None:
            raise KeyError(decision_id)
        return Path(row["image_path"])


def decision_request(snapshot: dict[str, Any], image_data_url: str) -> dict[str, Any]:
    return {
        "model": "gpt-6-luna",
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Assess this frozen paper-trading chart only as decision "
                            "support. You are the analyst. Propose an action using "
                            "the chart image and matching snapshot. An upward SMA "
                            "crossover supports buying if cash covers one share; "
                            "a downward crossover supports selling or closing an "
                            "open position. Otherwise hold an open position or wait "
                            "flat. Do not place an order."
                        ),
                    },
                    {"type": "input_image", "image_url": image_data_url, "detail": "high"},
                    {"type": "input_json", "data": snapshot},
                ],
            }
        ],
        "questions": QUESTIONS,
    }


def supporting_facts(snapshot: dict[str, Any]) -> dict[str, Any]:
    position = snapshot["paper_position"]
    price = snapshot["candles"][-1]["close"]
    return {
        "symbol": snapshot["symbol"], "cutoff": snapshot["cutoff"],
        "price": price, "cash": position["cash"], "shares": position["shares"],
        "one_share_affordable": position["cash"] >= price,
        "python_crossover": snapshot["python_crossover"],
    }


def review_request(snapshot: dict[str, Any], image_data_url: str,
                   analyst_answers: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "model": "gpt-6-luna",
        "input": [{"role": "user", "content": [
            {"type": "input_text", "text": (
                "You are the independent reviewer. Check the analyst's actual "
                "named answers against the frozen image, snapshot, and backend "
                "facts. Return one named verdict. Do not place an order.")},
            {"type": "input_image", "image_url": image_data_url, "detail": "high"},
            {"type": "input_json", "data": {
                "snapshot": snapshot, "analyst_answers": analyst_answers,
                "backend_facts": supporting_facts(snapshot),
            }},
        ]}],
        "questions": REVIEW_QUESTIONS,
    }


def validate_review(response: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    answers = response.get("answers")
    if not isinstance(answers, list):
        return [], "Reviewer omitted its named verdict."
    named = [a for a in answers if isinstance(a, dict) and a.get("name") == "verdict"]
    if len(named) != 1:
        return named, "Reviewer must return exactly one named verdict."
    allowed = {choice["value"] for choice in REVIEW_QUESTIONS[0]["choices"]}
    if named[0].get("choice") not in allowed:
        return named, "Reviewer returned an invalid verdict."
    return named, None


def final_rule_check(snapshot: dict[str, Any], analyst_answers: list[dict[str, Any]],
                     reviewer_answers: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    facts = supporting_facts(snapshot)
    choices = {answer["name"]: answer.get("choice") for answer in analyst_answers}
    verdict = reviewer_answers[0]["choice"] if reviewer_answers else None
    action = choices.get("action")
    signal = facts["python_crossover"]["signal"]
    shares = facts["shares"]
    reasons = []
    if not facts["python_crossover"]["available"]:
        reasons.append("Python has no comparable SMA crossover at the cutoff.")
    if action == "buy":
        if signal != "upward":
            reasons.append(f"Buy requires an upward crossover; observed {signal}.")
        if not facts["one_share_affordable"]:
            reasons.append(f"Cash {facts['cash']} is below one share at {facts['price']}.")
    elif action in ("sell", "close"):
        if signal != "downward" or shares < 1:
            reasons.append(f"{action} requires a downward crossover and shares; observed {signal}, {shares} shares.")
    elif action == "hold":
        if shares < 1 or signal != "none":
            reasons.append(f"Hold requires shares and no crossover; observed {shares} shares, {signal}.")
    elif action == "wait":
        if shares != 0 or signal == "upward":
            reasons.append(f"Wait requires a flat position without an upward crossover; observed {shares} shares, {signal}.")
    else:
        reasons.append("Analyst action is missing or invalid.")
    rules_passed = not reasons
    if verdict != "accept":
        reasons.append(f"Reviewer verdict: {verdict or 'missing'}; Python observed {shares} shares, cash {facts['cash']}, price {facts['price']}, and {signal} crossover.")
    return {"action": action, "reviewer_verdict": verdict, "facts": facts,
            "rules_passed": rules_passed, "passed": not reasons}, reasons


def call_decision_provider(
    request_body: dict[str, Any],
    *,
    url: str,
    api_key: str | None,
    timeout: float = 30,
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(
        f"{url.rstrip('/')}/decisions",
        data=_canonical(request_body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        raise ValueError(f"Decision provider returned HTTP {error.code}: {detail}") from error
    except (URLError, OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Decision provider request failed: {error}") from error


def validate_answers(response: dict[str, Any], snapshot: dict[str, Any]) -> tuple[list[dict[str, Any]], bool, list[str]]:
    answers = response.get("answers")
    if not isinstance(answers, list):
        answers = []
    by_name: dict[str, dict[str, Any]] = {}
    duplicate_names: set[str] = set()
    for answer in answers:
        if not isinstance(answer, dict) or not isinstance(answer.get("name"), str):
            continue
        if answer["name"] in by_name:
            duplicate_names.add(answer["name"])
        by_name[answer["name"]] = answer

    reasons: list[str] = []
    expected_names = {question["name"] for question in QUESTIONS}
    missing = sorted(expected_names - set(by_name))
    if missing:
        reasons.append(f"Missing named answers: {', '.join(missing)}.")
    if duplicate_names:
        reasons.append(f"Duplicate named answers: {', '.join(sorted(duplicate_names))}.")

    normalized = []
    for question in QUESTIONS:
        answer = by_name.get(question["name"])
        if answer is None:
            normalized.append({"name": question["name"], "choice": None})
            continue
        choice = answer.get("choice")
        allowed = {item["value"] for item in question["choices"]}
        if choice not in allowed:
            reasons.append(f"Invalid {question['name']} answer: {choice!r}.")
        normalized.append({**answer, "name": question["name"], "choice": choice})

    choices = {item["name"]: item.get("choice") for item in normalized}
    if choices.get("crossover") == "unreadable" or choices.get("evidence") == "unreadable":
        reasons.append("The provider marked the chart image unreadable.")
    if choices.get("evidence") != "sufficient":
        reasons.append("The visible chart was not judged sufficient evidence.")
    python_signal = snapshot["python_crossover"]["signal"]
    if choices.get("crossover") not in {None, "unreadable", python_signal}:
        reasons.append(
            f"Visual crossover {choices.get('crossover')} conflicts with Python {python_signal}."
        )
    return normalized, not reasons, reasons


def provider_settings() -> tuple[str, str, str | None]:
    provider = os.getenv("DECISION_PROVIDER", "openai").strip().lower()
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    api_key = os.getenv("OPENAI_API_KEY")
    if provider == "openai" and not api_key:
        raise ValueError(
            "OPENAI_API_KEY is not set. Add it to the backend environment, then retry the live image request."
        )
    return provider, base_url, api_key
