from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any, Callable


INDICATOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS indicator_instances (
    indicator_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL,
    indicator_type TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    UNIQUE (symbol, timeframe, name_key)
);

CREATE INDEX IF NOT EXISTS idx_indicator_chart
    ON indicator_instances(symbol, timeframe, indicator_id);
"""


@dataclass(frozen=True)
class IndicatorDefinition:
    key: str
    label: str
    description: str
    inputs: tuple[dict[str, str], ...]
    units: str
    calculate_window: Callable[[list[dict[str, Any]]], float]

    def public_contract(self) -> dict[str, Any]:
        return {
            "type": self.key,
            "label": self.label,
            "description": self.description,
            "inputs": list(self.inputs),
            "units": self.units,
            "settings": {
                "window": {
                    "type": "integer",
                    "minimum": 1,
                    "units": "completed candles",
                }
            },
            "output": (
                "One numeric value in the declared units, or null at each candle "
                "time while the window is warming up or that candle is not complete."
            ),
        }


def _sma(window: list[dict[str, Any]]) -> float:
    return sum(float(candle["close"]) for candle in window) / len(window)


def _price_range(window: list[dict[str, Any]]) -> float:
    highest_high = max(float(candle["high"]) for candle in window)
    lowest_low = min(float(candle["low"]) for candle in window)
    return highest_high - lowest_low


INDICATOR_TYPES: dict[str, IndicatorDefinition] = {
    "sma": IndicatorDefinition(
        key="sma",
        label="Simple moving average",
        description="Arithmetic mean of close prices over N completed candles.",
        inputs=({"field": "close", "units": "price"},),
        units="price",
        calculate_window=_sma,
    ),
    "price_range": IndicatorDefinition(
        key="price_range",
        label="Rolling price range",
        description=(
            "Highest high minus lowest low over N completed candles."
        ),
        inputs=(
            {"field": "high", "units": "price"},
            {"field": "low", "units": "price"},
        ),
        units="price difference",
        calculate_window=_price_range,
    ),
}


def indicator_type_contracts() -> dict[str, Any]:
    return {
        "input_contract": {
            "candles": (
                "Ordered candles with timestamp, open, high, low, close, and volume; "
                "only candles whose interval_ended flag is true enter a window."
            ),
            "settings": "Settings are validated for the selected type before calculation.",
        },
        "output_contract": (
            "Every source candle time receives one numeric value or a null warm-up gap."
        ),
        "types": [definition.public_contract() for definition in INDICATOR_TYPES.values()],
    }


def validate_indicator(
    indicator_type: str,
    name: Any,
    settings: Any,
) -> tuple[str, dict[str, int]]:
    normalized_type = str(indicator_type).strip().lower()
    if normalized_type not in INDICATOR_TYPES:
        available = ", ".join(INDICATOR_TYPES)
        raise ValueError(f"Unknown indicator type. Available types: {available}.")

    normalized_name = str(name).strip()
    if not normalized_name:
        raise ValueError("Indicator name is required.")
    if len(normalized_name) > 80:
        raise ValueError("Indicator name must be 80 characters or fewer.")
    if not isinstance(settings, dict):
        raise ValueError("Indicator settings must be an object.")
    if set(settings) != {"window"}:
        raise ValueError("Indicator settings must contain only window.")
    window = settings.get("window")
    if isinstance(window, bool) or not isinstance(window, int):
        raise ValueError("Window must be a whole number of completed candles.")
    if window < 1:
        raise ValueError("Window must be at least 1 completed candle.")
    if window > 10_000:
        raise ValueError("Window must be 10,000 completed candles or fewer.")
    return normalized_name, {"window": window}


def calculate_indicator(
    indicator_type: str,
    settings: dict[str, Any],
    candles: list[dict[str, Any]],
    status: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized_type = str(indicator_type).strip().lower()
    _, validated = validate_indicator(normalized_type, "calculation", settings)
    definition = INDICATOR_TYPES[normalized_type]
    status_by_time = {item["timestamp"]: item for item in status}
    completed: list[dict[str, Any]] = []
    values: list[dict[str, Any]] = []
    window_size = validated["window"]

    for candle in candles:
        candle_status = status_by_time.get(candle["timestamp"], {})
        interval_ended = candle_status.get("interval_ended") is True
        value: float | None = None
        if interval_ended:
            completed.append(candle)
            if len(completed) >= window_size:
                value = definition.calculate_window(completed[-window_size:])
        values.append({"timestamp": candle["timestamp"], "value": value})
    return values


@dataclass(frozen=True)
class IndicatorInstance:
    indicator_id: int
    symbol: str
    timeframe: str
    name: str
    indicator_type: str
    settings: dict[str, int]
    created_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        output = asdict(self)
        output["type"] = output.pop("indicator_type")
        return output


class IndicatorStore:
    def __init__(self, database_path: str | Path):
        self.path = Path(database_path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self._lock = RLock()
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(INDICATOR_SCHEMA)
        self.connection.commit()

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    def __enter__(self) -> "IndicatorStore":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def create(
        self,
        symbol: str,
        timeframe: str,
        name: str,
        indicator_type: str,
        settings: dict[str, Any],
    ) -> IndicatorInstance:
        normalized_type = str(indicator_type).strip().lower()
        normalized_name, validated = validate_indicator(
            normalized_type,
            name,
            settings,
        )
        created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        try:
            with self._lock, self.connection:
                cursor = self.connection.execute(
                    """
                    INSERT INTO indicator_instances (
                        symbol, timeframe, name, name_key, indicator_type,
                        settings_json, created_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        symbol.strip().upper(),
                        timeframe,
                        normalized_name,
                        normalized_name.casefold(),
                        normalized_type,
                        json.dumps(validated, sort_keys=True, separators=(",", ":")),
                        created_at,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(
                f'An indicator named "{normalized_name}" already exists for this chart.'
            ) from error
        return self.get(int(cursor.lastrowid))

    def get(self, indicator_id: int) -> IndicatorInstance:
        with self._lock:
            row = self.connection.execute(
                "SELECT * FROM indicator_instances WHERE indicator_id = ?",
                (indicator_id,),
            ).fetchone()
        if row is None:
            raise KeyError(indicator_id)
        return self._instance(row)

    def update_settings(self, indicator_id: int, settings: dict[str, Any]) -> IndicatorInstance:
        instance = self.get(indicator_id)
        _, validated = validate_indicator(instance.indicator_type, instance.name, settings)
        with self._lock, self.connection:
            self.connection.execute(
                "UPDATE indicator_instances SET settings_json = ? WHERE indicator_id = ?",
                (json.dumps(validated, sort_keys=True, separators=(",", ":")), indicator_id),
            )
        return self.get(indicator_id)

    def list(self, symbol: str, timeframe: str) -> list[IndicatorInstance]:
        with self._lock:
            rows = self.connection.execute(
                """
                SELECT * FROM indicator_instances
                WHERE symbol = ? AND timeframe = ?
                ORDER BY indicator_id
                """,
                (symbol.strip().upper(), timeframe),
            ).fetchall()
        return [self._instance(row) for row in rows]

    @staticmethod
    def _instance(row: sqlite3.Row) -> IndicatorInstance:
        return IndicatorInstance(
            indicator_id=int(row["indicator_id"]),
            symbol=row["symbol"],
            timeframe=row["timeframe"],
            name=row["name"],
            indicator_type=row["indicator_type"],
            settings=json.loads(row["settings_json"]),
            created_at_utc=row["created_at_utc"],
        )


def instance_with_values(
    instance: IndicatorInstance,
    candles: list[dict[str, Any]],
    status: list[dict[str, Any]],
) -> dict[str, Any]:
    definition = INDICATOR_TYPES[instance.indicator_type]
    return {
        **instance.to_dict(),
        "units": definition.units,
        "values": calculate_indicator(
            instance.indicator_type,
            instance.settings,
            candles,
            status,
        ),
    }
