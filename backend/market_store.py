import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any


DEFAULT_DATABASE = Path(__file__).resolve().parent / "data" / "market-observations.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    source_time_raw TEXT,
    source_time_epoch_ms INTEGER,
    source_time_utc TEXT,
    source_time_units TEXT NOT NULL,
    price REAL,
    day_volume INTEGER,
    last_size INTEGER,
    raw_payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    relationship TEXT NOT NULL CHECK (
        relationship IN ('new', 'distinct_same_source_time', 'revision')
    ),
    supersedes_observation_id INTEGER REFERENCES observations(observation_id),
    UNIQUE (ticker, payload_hash)
);

CREATE TABLE IF NOT EXISTS receipts (
    receipt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_id INTEGER NOT NULL REFERENCES observations(observation_id),
    backend_receipt_time_utc TEXT NOT NULL,
    is_exact_repeat INTEGER NOT NULL CHECK (is_exact_repeat IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_observations_source_time
    ON observations(ticker, source_time_epoch_ms, observation_id);

CREATE INDEX IF NOT EXISTS idx_receipts_arrival
    ON receipts(receipt_id, backend_receipt_time_utc);
"""


@dataclass(frozen=True)
class RecordResult:
    observation_id: int
    receipt_id: int
    action: str
    is_exact_repeat: bool
    payload_hash: str
    supersedes_observation_id: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_integer(value: Any) -> int | None:
    if value in (None, ""):
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def describe_source_time(value: Any) -> dict[str, Any]:
    raw_value = parse_integer(value)
    if raw_value is None:
        return {
            "source_time_raw": None,
            "source_time_epoch_ms": None,
            "source_time_utc": None,
            "source_time_units": "not supplied",
        }

    if raw_value >= 10_000_000_000:
        epoch_ms = raw_value
        units = "Unix epoch milliseconds"
    else:
        epoch_ms = raw_value * 1000
        units = "Unix epoch seconds"

    source_time_utc = datetime.fromtimestamp(
        epoch_ms / 1000,
        tz=timezone.utc,
    ).isoformat().replace("+00:00", "Z")
    return {
        "source_time_raw": str(raw_value),
        "source_time_epoch_ms": epoch_ms,
        "source_time_utc": source_time_utc,
        "source_time_units": units,
    }


def normalize_receipt_time(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("backend receipt time must be timezone-aware")

    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_payload(message: dict[str, Any]) -> tuple[str, str]:
    payload_json = json.dumps(
        message,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    return payload_json, payload_hash


class MarketRecorder:
    def __init__(self, database_path: str | Path = DEFAULT_DATABASE):
        if str(database_path) == ":memory:":
            self.path = Path(":memory:")
            connection_target: str | Path = ":memory:"
        else:
            self.path = Path(database_path).expanduser().resolve()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection_target = self.path
        self.connection = sqlite3.connect(connection_target)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "MarketRecorder":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def record_message(
        self,
        message: dict[str, Any],
        backend_receipt_time: datetime,
        ticker: str | None = None,
        supersedes_observation_id: int | None = None,
    ) -> RecordResult:
        symbol = str(message.get("id") or ticker or "").strip().upper()
        if not symbol:
            raise ValueError("ticker is required in message['id'] or ticker")

        payload_json, payload_hash = canonical_payload(message)
        source_time = describe_source_time(message.get("time"))
        receipt_time = normalize_receipt_time(backend_receipt_time)

        with self.connection:
            existing = self.connection.execute(
                """
                SELECT observation_id, supersedes_observation_id
                FROM observations
                WHERE ticker = ? AND payload_hash = ?
                """,
                (symbol, payload_hash),
            ).fetchone()

            if existing is not None:
                observation_id = int(existing["observation_id"])
                receipt_id = self._insert_receipt(
                    observation_id,
                    receipt_time,
                    is_exact_repeat=True,
                )
                return RecordResult(
                    observation_id=observation_id,
                    receipt_id=receipt_id,
                    action="exact_repeat",
                    is_exact_repeat=True,
                    payload_hash=payload_hash,
                    supersedes_observation_id=existing["supersedes_observation_id"],
                )

            relationship = self._relationship_for_new_payload(
                symbol,
                source_time["source_time_raw"],
                supersedes_observation_id,
            )
            cursor = self.connection.execute(
                """
                INSERT INTO observations (
                    ticker,
                    source_time_raw,
                    source_time_epoch_ms,
                    source_time_utc,
                    source_time_units,
                    price,
                    day_volume,
                    last_size,
                    raw_payload_json,
                    payload_hash,
                    relationship,
                    supersedes_observation_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    source_time["source_time_raw"],
                    source_time["source_time_epoch_ms"],
                    source_time["source_time_utc"],
                    source_time["source_time_units"],
                    message.get("price"),
                    parse_integer(message.get("day_volume")),
                    parse_integer(message.get("last_size")),
                    payload_json,
                    payload_hash,
                    relationship,
                    supersedes_observation_id,
                ),
            )
            observation_id = int(cursor.lastrowid)
            receipt_id = self._insert_receipt(
                observation_id,
                receipt_time,
                is_exact_repeat=False,
            )
            return RecordResult(
                observation_id=observation_id,
                receipt_id=receipt_id,
                action=relationship,
                is_exact_repeat=False,
                payload_hash=payload_hash,
                supersedes_observation_id=supersedes_observation_id,
            )

    def _relationship_for_new_payload(
        self,
        ticker: str,
        source_time_raw: str | None,
        supersedes_observation_id: int | None,
    ) -> str:
        if supersedes_observation_id is not None:
            prior = self.connection.execute(
                """
                SELECT ticker, source_time_raw
                FROM observations
                WHERE observation_id = ?
                """,
                (supersedes_observation_id,),
            ).fetchone()
            if prior is None:
                raise ValueError("superseded observation does not exist")
            if prior["ticker"] != ticker or prior["source_time_raw"] != source_time_raw:
                raise ValueError(
                    "a revision must match the prior observation ticker and source time"
                )
            return "revision"

        same_source_time = self.connection.execute(
            """
            SELECT 1
            FROM observations
            WHERE ticker = ? AND source_time_raw IS ?
            LIMIT 1
            """,
            (ticker, source_time_raw),
        ).fetchone()
        return "distinct_same_source_time" if same_source_time else "new"

    def _insert_receipt(
        self,
        observation_id: int,
        backend_receipt_time_utc: str,
        is_exact_repeat: bool,
    ) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO receipts (
                observation_id,
                backend_receipt_time_utc,
                is_exact_repeat
            ) VALUES (?, ?, ?)
            """,
            (observation_id, backend_receipt_time_utc, int(is_exact_repeat)),
        )
        return int(cursor.lastrowid)

    def list_observations(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT
                observations.*,
                COUNT(receipts.receipt_id) AS receipt_count,
                MIN(receipts.receipt_id) AS first_receipt_id,
                MAX(receipts.receipt_id) AS last_receipt_id,
                MIN(receipts.backend_receipt_time_utc) AS first_receipt_time_utc,
                MAX(receipts.backend_receipt_time_utc) AS last_receipt_time_utc
            FROM observations
            JOIN receipts USING (observation_id)
            GROUP BY observations.observation_id
            ORDER BY observations.observation_id
            """
        ).fetchall()
        observations = []
        for row in rows:
            observation = dict(row)
            observation["raw_payload"] = json.loads(
                observation.pop("raw_payload_json")
            )
            observations.append(observation)
        return observations

    def list_receipts(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT
                receipts.receipt_id,
                receipts.observation_id,
                observations.ticker,
                observations.source_time_raw,
                observations.source_time_utc,
                receipts.backend_receipt_time_utc,
                receipts.is_exact_repeat
            FROM receipts
            JOIN observations USING (observation_id)
            ORDER BY receipts.receipt_id
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def list_effective_observations(self, ticker: str, as_of: datetime | None = None) -> list[dict[str, Any]]:
        """Return one ticker's current observations in source-time order.

        An observation explicitly superseded by a correction remains stored for
        audit purposes but is excluded from derived market data. Exact repeats
        already share one observation row and therefore appear only once here.
        """
        rows = self.connection.execute(
            """
            SELECT observations.*
            FROM observations
            WHERE observations.ticker = ?
              AND observations.source_time_epoch_ms IS NOT NULL
              AND observations.price IS NOT NULL
              AND EXISTS (SELECT 1 FROM receipts r WHERE r.observation_id = observations.observation_id
                          AND (? IS NULL OR julianday(r.backend_receipt_time_utc) <= julianday(?)))
              AND NOT EXISTS (
                  SELECT 1
                  FROM observations AS corrections
                  WHERE corrections.supersedes_observation_id =
                        observations.observation_id
                    AND EXISTS (SELECT 1 FROM receipts r WHERE r.observation_id = corrections.observation_id
                                AND (? IS NULL OR julianday(r.backend_receipt_time_utc) <= julianday(?)))
              )
            ORDER BY observations.source_time_epoch_ms, observations.observation_id
            """,
            (ticker.strip().upper(), *([normalize_receipt_time(as_of) if as_of else None] * 4)),
        ).fetchall()
        return [dict(row) for row in rows]


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize or inspect market storage.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--init", action="store_true")
    action.add_argument("--show", choices=("observations", "receipts", "all"))
    arguments = parser.parse_args()

    with MarketRecorder(arguments.database) as recorder:
        if arguments.init:
            output: dict[str, Any] = {
                "database": str(recorder.path),
                "initialized": True,
            }
        elif arguments.show == "observations":
            output = {"database": str(recorder.path), "observations": recorder.list_observations()}
        elif arguments.show == "receipts":
            output = {"database": str(recorder.path), "receipts": recorder.list_receipts()}
        else:
            output = {
                "database": str(recorder.path),
                "observations": recorder.list_observations(),
                "receipts": recorder.list_receipts(),
            }

    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
