"""Restricted local proxy for exposing only the GitLab webhook endpoint.

Usage:
    python tools/webhook_proxy.py --listen-port 8091 --target http://localhost:8090
"""

from __future__ import annotations

import argparse
import http.server
import socketserver
import urllib.error
import urllib.request


ALLOWED_PATH = "/webhook/gitlab"


class WebhookProxyHandler(http.server.BaseHTTPRequestHandler):
    target_base: str

    def do_GET(self) -> None:
        if self.path in ("/", "/healthz"):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
            return
        self.send_error(404, "Not Found")

    def do_POST(self) -> None:
        if self.path != ALLOWED_PATH:
            self.send_error(404, "Not Found")
            return

        content_length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(content_length)
        target_url = f"{self.target_base.rstrip('/')}{ALLOWED_PATH}"

        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower()
            in {
                "content-type",
                "x-gitlab-event",
                "x-gitlab-token",
                "user-agent",
            }
        }

        request = urllib.request.Request(target_url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                response_body = response.read()
                self.send_response(response.status)
                for key, value in response.headers.items():
                    if key.lower() not in {"transfer-encoding", "connection"}:
                        self.send_header(key, value)
                self.end_headers()
                self.wfile.write(response_body)
        except urllib.error.HTTPError as exc:
            response_body = exc.read()
            self.send_response(exc.code)
            self.end_headers()
            self.wfile.write(response_body)
        except Exception as exc:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(str(exc).encode("utf-8", errors="replace"))

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=8091)
    parser.add_argument("--target", default="http://localhost:8090")
    args = parser.parse_args()

    WebhookProxyHandler.target_base = args.target
    with socketserver.ThreadingTCPServer(
        (args.listen_host, args.listen_port),
        WebhookProxyHandler,
    ) as server:
        print(
            f"restricted webhook proxy listening on "
            f"http://{args.listen_host}:{args.listen_port}{ALLOWED_PATH} "
            f"-> {args.target}{ALLOWED_PATH}",
            flush=True,
        )
        server.serve_forever()


if __name__ == "__main__":
    main()
