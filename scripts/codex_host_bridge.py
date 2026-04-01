from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from roughcut.host.codex_bridge import run_codex_exec


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _make_handler(expected_token: str):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.rstrip("/") == "/healthz":
                _json_response(self, HTTPStatus.OK, {"status": "ok"})
                return
            _json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def do_POST(self):
            if self.path.rstrip("/") != "/v1/codex/exec":
                _json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            auth_header = str(self.headers.get("Authorization") or "").strip()
            if expected_token and auth_header != f"Bearer {expected_token}":
                _json_response(self, HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                return
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
                if not isinstance(payload, dict):
                    raise ValueError("payload must be an object")
                result = run_codex_exec(payload)
            except Exception as exc:
                _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            _json_response(self, HTTPStatus.OK, result)

        def log_message(self, format: str, *args):
            return

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description="Host-side Codex bridge for RoughCut Docker ACP.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=38695)
    parser.add_argument("--token", default="")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), _make_handler(args.token))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
