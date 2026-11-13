"""Offline voice-session check using a saved decision and a mocked provider."""

import argparse
from io import BytesIO
import json
from pathlib import Path
import sqlite3
from unittest.mock import patch
from urllib.error import URLError

from backend.voice import create_live_session, decision_summary, list_decision_summaries


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--decision-id", required=True)
    args = parser.parse_args()
    database = args.database.resolve()
    with sqlite3.connect(database) as connection:
        before = tuple(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                       for table in ("decision_records", "paper_orders", "paper_fills"))
    summary = decision_summary(database, args.decision_id)
    assert summary["decision_id"] == args.decision_id
    assert any(item["decision_id"] == args.decision_id for item in list_decision_summaries(database))
    fake_answer = {"session": {"id": "live_mock"},
                   "transport": {"type": "webrtc", "sdp": "v=0\r\nmock answer"}}
    with patch("backend.voice.urlopen", return_value=BytesIO(json.dumps(fake_answer).encode())) as mock_urlopen:
        result = create_live_session("v=0\r\nmock offer", summary,
                                     api_key="test-key", base_url="https://example.invalid/v1")
    request = mock_urlopen.call_args.args[0]
    payload = json.loads(request.data)
    assert request.full_url == "https://example.invalid/v1/live/sessions"
    assert payload["session"]["model"] == "gpt-live-1"
    assert payload["transport"] == {"type": "webrtc", "sdp": "v=0\r\nmock offer"}
    assert args.decision_id in payload["session"]["input"][0]["content"][0]["text"]
    assert result == {"session_id": "live_mock", "answer_sdp": "v=0\r\nmock answer"}
    with patch("backend.voice.urlopen", side_effect=URLError("mocked disconnect")):
        try:
            create_live_session("v=0\r\nmock offer", summary, api_key="test-key",
                                base_url="https://example.invalid/v1")
        except ValueError as error:
            assert str(error) == "Voice provider connection failed or timed out."
        else:
            raise AssertionError("Disconnected provider was accepted")
    with sqlite3.connect(database) as connection:
        after = tuple(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in ("decision_records", "paper_orders", "paper_fills"))
    assert before == after
    print(json.dumps({"decision_id": args.decision_id, "analyst": summary["analyst"]["action"],
                      "reviewer": summary["reviewer"]["verdict"],
                      "paper_outcome": summary["paper_outcome"],
                      "provider": "mocked", "session_id": result["session_id"],
                      "mocked_connection_failure": "rejected",
                      "record_counts_before": before, "record_counts_after": after}))


if __name__ == "__main__":
    main()
