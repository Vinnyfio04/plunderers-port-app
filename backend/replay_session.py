from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from backend.candle_aggregation import aggregate_ticker
from backend.market_store import MarketRecorder
from backend.timeframe_history import MinuteRecord, Timeframe, aggregate_timeframe


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("replay times must include a timezone")
    return parsed.astimezone(timezone.utc)


class RecordedSessionReader:
    """Read recorded observations without opening the source database for writes."""

    def __init__(self, database_path: str | Path):
        self.path = Path(database_path).expanduser().resolve()

    def _connect(self) -> sqlite3.Connection:
        if not self.path.exists():
            raise FileNotFoundError(self.path)
        connection = sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    def selections(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    observations.ticker,
                    MIN(observations.source_time_utc) AS first_source_time,
                    MAX(observations.source_time_utc) AS last_source_time,
                    COUNT(DISTINCT observations.observation_id) AS observations,
                    COUNT(receipts.receipt_id) AS receipts
                FROM observations
                JOIN receipts USING (observation_id)
                WHERE observations.source_time_epoch_ms IS NOT NULL
                GROUP BY observations.ticker
                ORDER BY observations.ticker
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def observation_count(self) -> int:
        if not self.path.exists():
            return 0
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0])

    def events(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    receipts.receipt_id,
                    receipts.backend_receipt_time_utc,
                    receipts.is_exact_repeat,
                    observations.observation_id,
                    observations.source_time_utc,
                    observations.raw_payload_json,
                    observations.relationship,
                    observations.supersedes_observation_id
                FROM receipts
                JOIN observations USING (observation_id)
                WHERE observations.ticker = ?
                  AND observations.source_time_epoch_ms >= ?
                  AND observations.source_time_epoch_ms < ?
                ORDER BY receipts.receipt_id
                """,
                (symbol.strip().upper(), start_ms, end_ms),
            ).fetchall()
        events = []
        for row in rows:
            event = dict(row)
            event["raw_payload"] = json.loads(event.pop("raw_payload_json"))
            events.append(event)
        return events


class ReplayEngine:
    def __init__(self, database_path: str | Path):
        self.reader = RecordedSessionReader(database_path)

    def replay(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> dict[str, Any]:
        events = self.reader.events(symbol, start, end)
        stored_count_before = self.reader.observation_count()
        if not events:
            return {
                "symbol": symbol,
                "interval": timeframe,
                "events": [],
                "stored_observation_count_before": stored_count_before,
                "stored_observation_count_after": self.reader.observation_count(),
            }

        replay_messages: list[dict[str, Any]] = []
        source_to_replay_id: dict[int, int] = {}
        previous_candles: dict[str, dict[str, Any]] = {}
        previous_status: dict[str, dict[str, Any]] = {}
        with MarketRecorder(":memory:") as replay_store:
            for sequence, event in enumerate(events, start=1):
                receipt_time = parse_utc(event["backend_receipt_time_utc"])
                source_observation_id = int(event["observation_id"])
                source_supersedes = event["supersedes_observation_id"]
                replay_supersedes = (
                    source_to_replay_id.get(int(source_supersedes))
                    if source_supersedes is not None
                    else None
                )
                result = replay_store.record_message(
                    event["raw_payload"],
                    receipt_time,
                    ticker=symbol,
                    supersedes_observation_id=replay_supersedes,
                )
                source_to_replay_id.setdefault(
                    source_observation_id,
                    result.observation_id,
                )

                one_minute = aggregate_ticker(replay_store, symbol, receipt_time)
                minute_records = [
                    MinuteRecord(candle=candle, available_at=receipt_time)
                    for candle in one_minute.candles
                ]
                aggregated = aggregate_timeframe(
                    minute_records,
                    timeframe=timeframe,
                    as_of=receipt_time,
                )
                status_by_timestamp = {
                    item["timestamp"]: item for item in aggregated["status"]
                }
                changed = []
                for candle in aggregated["candles"]:
                    candle_status = status_by_timestamp[candle["timestamp"]]
                    if (previous_candles.get(candle["timestamp"]) != candle
                            or previous_status.get(candle["timestamp"]) != candle_status):
                        changed.append(
                            {
                                "candle": candle,
                                "completion": candle_status,
                            }
                        )
                    previous_candles[candle["timestamp"]] = candle
                    previous_status[candle["timestamp"]] = candle_status

                replay_messages.append(
                    {
                        "type": "replay_observation",
                        "mode": "Replay",
                        "source": "Recorded SQLite session",
                        "feed_status": "disconnected",
                        "symbol": symbol,
                        "interval": timeframe,
                        "sequence": sequence,
                        "total": len(events),
                        "receipt_id": event["receipt_id"],
                        "observation_id": source_observation_id,
                        "market_price": event["raw_payload"].get("price"),
                        "replay_observation_time": event["source_time_utc"],
                        "replay_receipt_time": event["backend_receipt_time_utc"],
                        "relationship": event["relationship"],
                        "is_exact_repeat": bool(event["is_exact_repeat"]),
                        "updates": changed,
                    }
                )

        return {
            "mode": "Replay",
            "read_only": True,
            "symbol": symbol,
            "interval": timeframe,
            "events": replay_messages,
            "final_candles": list(previous_candles.values()),
            "stored_observation_count_before": stored_count_before,
            "stored_observation_count_after": self.reader.observation_count(),
        }
