import argparse
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
from pathlib import Path
import struct


class Handler(BaseHTTPRequestHandler):
    record_path: Path

    def do_POST(self) -> None:
        if self.path != "/v1/decisions":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        message = payload["input"][0]
        parts = {part["type"]: part for part in message["content"]}
        image = base64.b64decode(parts["input_image"]["image_url"].split(",", 1)[1])
        data = parts["input_json"]["data"]
        snapshot = data.get("snapshot", data)
        width, height = struct.unpack(">II", image[16:24])
        received = {
            "snapshot_id": snapshot["snapshot_id"],
            "png_signature_valid": image[:8] == b"\x89PNG\r\n\x1a\n",
            "png_width": width,
            "png_height": height,
            "png_sha256": hashlib.sha256(image).hexdigest(),
            "input_part_types": [part["type"] for part in message["content"]],
            "question_names": [item["name"] for item in payload["questions"]],
            "analyst_answers_received": data.get("analyst_answers", []),
        }
        self.record_path.write_text(json.dumps(received, indent=2), encoding="utf-8")
        shares = snapshot["paper_position"]["shares"]
        review = [item["name"] for item in payload["questions"]] == ["verdict"]
        response = {
            "model": payload["model"],
            "answers": ([{"type": "choice", "name": "verdict", "choice": "accept"}] if review else [
                {"type": "choice", "name": "action", "choice": "buy" if snapshot["python_crossover"]["signal"] == "upward" else "hold" if shares else "wait"},
                {
                    "type": "choice",
                    "name": "crossover",
                    "choice": snapshot["python_crossover"]["signal"],
                },
                {"type": "choice", "name": "evidence", "choice": "sufficient"},
            ]),
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        }
        body = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8011)
    parser.add_argument("--record", type=Path, required=True)
    args = parser.parse_args()
    Handler.record_path = args.record.expanduser().resolve()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Decision provider test double listening on http://{args.host}:{args.port}/v1")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
