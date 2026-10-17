"""Additive offline analysis page/API in the existing loopback console application."""

import argparse
import hmac
import html
import json
import secrets
from functools import partial
from http.server import ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import unquote, urlsplit

from agent_console.server import Handler, Store


def asset(name):
    if name not in {"analysis.html", "analysis.css", "analysis.js"}:
        raise ValueError("Unknown analysis asset")
    packaged = files("agent_console").joinpath("static", name)
    return (
        packaged.read_bytes()
        if packaged.is_file()
        else (Path(__file__).resolve().parents[2] / "static" / name).read_bytes()
    )


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate request field")
        result[key] = value
    return result


class AnalysisHandler(Handler):
    def __init__(self, *args, analysis, token, **kwargs):
        self.analysis, self.token = analysis, token
        super().__init__(*args, **kwargs)

    def origin(self, *, mutation=False):
        host = self.headers.get("Host", "")
        if (
            host
            not in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            or self.headers.get("Origin", f"http://{host}" if not mutation else "")
            != f"http://{host}"
        ):
            raise PermissionError("Same-origin loopback access required")

    def do_GET(self):
        path = unquote(urlsplit(self.path).path)
        if not (path.startswith("/api/analysis") or path.startswith("/analysis")):
            return super().do_GET()
        try:
            self.origin()
            if path in {"/analysis", "/analysis/", "/analysis.js", "/analysis.css"}:
                name = "analysis.html" if path in {"/analysis", "/analysis/"} else path[1:]
                media = {
                    "analysis.html": "text/html",
                    "analysis.js": "text/javascript",
                    "analysis.css": "text/css",
                }[name]
                return self.respond(asset(name), media + "; charset=utf-8")
            parts = path.strip("/").split("/")
            if path == "/api/analysis":
                from agent_runtime.tasks.repository_analysis import QUESTIONS, SAMPLE
                from agent_runtime.tasks.repository_analysis_sdk import LIVE_ANALYSIS_ENABLED

                return self.json(
                    {
                        "csrf": self.token,
                        "mode": "offline-scripted-sample",
                        "model_requests": 0,
                        "sdk_live_enabled": LIVE_ANALYSIS_ENABLED,
                        "repositories": [
                            {
                                "id": "tiny-shop",
                                "label": "Tiny Shop · approved local sample",
                                "files": list(SAMPLE),
                            }
                        ],
                        "questions": QUESTIONS,
                        "jobs": self.analysis.list(),
                    }
                )
            if len(parts) == 5 and parts[:3] == ["api", "analysis", "jobs"]:
                job_id, action = parts[3:]
                if action == "preview":
                    return self.json(self.analysis.preview(job_id))
                if action == "report":
                    return self.json(self.analysis.report(job_id))
                if action == "download":
                    return self.respond(
                        self.analysis.bundle(job_id),
                        "application/zip",
                        attachment="repository-analysis.zip",
                    )
            if len(parts) == 6 and parts[:3] == ["api", "analysis", "jobs"] and parts[4] == "files":
                source = self.analysis.sources(parts[3])
                name = parts[5]
                if name not in source:
                    raise ValueError("Only approved snapshot files are available")
                lines = "\n".join(
                    f'<span id="L{index}">{index:3} {html.escape(line)}</span>'
                    for index, line in enumerate(source[name].splitlines(), 1)
                )
                document = f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(name)}</title><link rel="stylesheet" href="/analysis.css"></head><body><main><a href="/analysis">Back to analysis</a><h1>{html.escape(name)}</h1><p>Immutable approved source snapshot</p><pre>{lines}</pre></main></body></html>'
                return self.respond(document.encode(), "text/html; charset=utf-8")
            self.json({"error": "Unknown analysis endpoint"}, 404)
        except PermissionError:
            self.json({"error": "Same-origin loopback access required"}, 403)
        except (ValueError, OSError, KeyError, TypeError):
            self.json({"error": "Analysis unavailable or failed source/report validation"}, 409)

    def do_POST(self):
        if not urlsplit(self.path).path.startswith("/api/analysis"):
            return super().do_POST()
        try:
            self.origin(mutation=True)
            if not hmac.compare_digest(self.headers.get("X-CAS-CSRF", ""), self.token):
                raise PermissionError("Analysis token required")
            length = int(self.headers.get("Content-Length", "0"))
            if (
                self.headers.get("Content-Type") != "application/json"
                or self.headers.get("Transfer-Encoding") is not None
                or not 0 < length <= 1024
            ):
                raise ValueError("Expected bounded JSON")
            self.connection.settimeout(5)
            value = json.loads(self.rfile.read(length), object_pairs_hook=unique)
            if type(value) is not dict:
                raise ValueError("Expected object")
            if self.path == "/api/analysis/jobs" and set(value) in (
                {"repository", "question"},
                {"repository", "question", "files", "mode"},
            ):
                return self.json(self.analysis.create(**value))
            parts = self.path.strip("/").split("/")
            if len(parts) == 5 and parts[:3] == ["api", "analysis", "jobs"]:
                if parts[4] == "start" and set(value) in (
                    set(),
                    {"allow_live", "allow_existing_login", "snapshot_sha256"},
                ):
                    return self.json(self.analysis.start(parts[3], **value))
                if parts[4] == "stop" and value == {}:
                    return self.json(self.analysis.stop(parts[3]))
            raise ValueError("Unknown analysis operation")
        except PermissionError:
            self.json({"error": "Same-origin token required"}, 403)
        except (ValueError, OSError, RuntimeError, KeyError, TypeError):
            self.json({"error": "Analysis operation rejected; refresh state"}, 409)


def create_analysis_server(controller, port=8766):
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("Invalid loopback port")
    handler = partial(
        AnalysisHandler,
        store=Store(controller.root),
        analysis=controller,
        token=secrets.token_urlsafe(32),
    )
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        required=True,
        help="Fresh dedicated offline analysis data directory",
    )
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("Port must be 1..65535")
    from agent_runtime.tasks.repository_analysis import AnalysisControl

    controller = AnalysisControl(args.data_dir)
    try:
        with create_analysis_server(controller, args.port) as server:
            print(
                f"CAS offline repository analysis: http://127.0.0.1:{server.server_port}/analysis",
                flush=True,
            )
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
    finally:
        controller.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
