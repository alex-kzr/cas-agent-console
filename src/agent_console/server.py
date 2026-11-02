"""Loopback-only stdlib HTTP server; no runtime imports or execution endpoints."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from itertools import islice
from pathlib import Path, PureWindowsPath
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker


class DataError(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def asset_bytes(name: str) -> bytes:
    if name not in {"index.html", "styles.css", "app.js", "tasks.js", "working-sessions.js"}:
        raise DataError("Unknown asset", 404)
    packaged = files("agent_console").joinpath("static", name)
    if packaged.is_file():
        return packaged.read_bytes()
    # Hatch's editable src package hides wheel force-included resources. Only the
    # owning checkout is a fallback; installed wheels always use packaged files.
    checkout = Path(__file__).resolve().parents[2]
    if not (checkout / "pyproject.toml").is_file():
        raise DataError("Console assets missing; reinstall application", 500)
    return (checkout / "static" / name).read_bytes()


def identifier(value: str) -> str:
    try:
        if str(UUID(value)) == value:
            return value
    except ValueError:
        pass
    raise DataError("Invalid identifier", 400)


class Store:
    def __init__(self, data_dir: Path):
        self.root = data_dir.resolve()

    def path(self, relative: str) -> Path:
        if (
            not relative
            or "\\" in relative
            or ":" in relative
            or "\x00" in relative
            or PureWindowsPath(relative).drive
            or relative.startswith("/")
            or any(part in {"", ".", ".."} for part in relative.split("/"))
        ):
            raise DataError("Invalid data reference", 400)
        for segment in relative.split("/"):
            if (
                segment != segment.rstrip(" .")
                or any(ord(character) < 32 for character in segment)
                or re.fullmatch(
                    r"(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])",
                    segment.split(".", 1)[0].rstrip(" "),
                    re.IGNORECASE,
                )
            ):
                raise DataError("Device or ambiguous data reference", 400)
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise DataError("Data reference escapes root", 400)
        return path

    def document(self, relative: str, schema: str) -> dict:
        path = self.path(relative)
        try:
            if path.stat().st_size > 1_000_000:
                raise DataError("Record exceeds size limit", 413)
            document = json.loads(path.read_text(encoding="utf-8"))
        except DataError:
            raise
        except FileNotFoundError as error:
            raise DataError("Record unavailable", 404) from error
        except (ValueError, OSError) as error:
            raise DataError("Corrupt or unreadable record") from error
        if not isinstance(document, dict):
            raise DataError("Expected an object record")
        if document.get("schema_version") != 1:
            raise DataError("Unsupported schema version", 409)
        definition = json.loads(
            files("agent_console.schemas").joinpath(f"{schema}.json").read_text()
        )
        validator = Draft202012Validator(definition, format_checker=FormatChecker())
        if next(validator.iter_errors(document), None):
            raise DataError("Record does not satisfy v1 contract")
        return document

    def run(self, run_id: str) -> dict:
        run_id = identifier(run_id)
        record = self.document(f"runs/{run_id}/run.json", "run")
        if record["run_id"] != run_id:
            raise DataError("Run identity mismatch")
        return record

    def runs(self, limit: int, offset: int) -> dict:
        records, warnings = [], []
        directories = (
            list(islice(self.path("runs").glob("*/run.json"), 5001))
            if self.path("runs").is_dir()
            else []
        )
        # Bound filesystem work as well as the HTTP response.
        truncated = len(directories) > 5000
        for file in directories[:5000]:
            try:
                records.append(self.run(file.parent.name))
            except DataError:
                warnings.append("A corrupt, unsupported or unsafe run was omitted")
        records.sort(key=lambda record: record["created_at"], reverse=True)
        if truncated:
            warnings.append("History capped at 5000 files")
        return {
            "runs": records[offset : offset + limit],
            "total": len(records),
            "warnings": warnings,
        }

    def detail(self, run_id: str) -> dict:
        record = self.run(run_id)
        result = {"run": record, "warnings": []}
        for filename, schema in (
            ("result", "result"),
            ("artifacts", "artifacts"),
            ("assertions", "assertions"),
        ):
            try:
                document = self.document(f"runs/{run_id}/{filename}.json", schema)
                if document["run_id"] != run_id:
                    raise DataError("Linked record identity mismatch")
                result[filename] = document
            except DataError as error:
                result[filename] = None
                if filename != "assertions" or record["kind"] == "scenario":
                    result["warnings"].append(f"{filename}: {error}")
        return result

    def events(self, run_id: str, after_seq: int, limit: int) -> dict:
        if limit < 1:
            raise DataError("Event limit must be positive", 400)
        self.run(run_id)
        path = self.path(f"runs/{run_id}/events.jsonl")
        if not path.is_file():
            return {"events": [], "warnings": ["Events unavailable"]}
        with path.open("rb") as stream:
            raw = stream.read(4_000_001)
        warnings = ["Event read capped at 4 MB"] if len(raw) > 4_000_000 else []
        events = []
        last_seq = 0
        schema = json.loads(
            files("agent_console.schemas").joinpath("event.json").read_text()
        )
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        for line in raw[:4_000_000].splitlines(keepends=True):
            if not line.endswith(b"\n"):
                warnings.append("Incomplete trailing event line")
                break
            if len(line) > 65_537:
                warnings.append("Oversize event omitted")
                continue
            try:
                event = json.loads(line)
                if (
                    not isinstance(event, dict)
                    or event.get("schema_version") != 1
                    or event.get("run_id") != run_id
                ):
                    raise ValueError("Unsupported event")
                if type(event.get("seq")) is not int:
                    raise ValueError("Invalid sequence")
                if next(validator.iter_errors(event), None):
                    raise ValueError("Invalid event envelope")
                if event["seq"] <= last_seq:
                    raise ValueError("Nonmonotonic event sequence")
                last_seq = event["seq"]
                if event["seq"] > after_seq:
                    events.append(event)
            except (ValueError, UnicodeError):
                warnings.append("Invalid event omitted")
        return {
            "events": events[:limit],
            "warnings": warnings,
            "more": len(events) > limit,
            "next_seq": events[min(len(events), limit) - 1]["seq"]
            if events
            else after_seq,
        }

    def artifact(self, run_id: str, artifact_id: str) -> tuple[bytes, str]:
        self.run(run_id)
        identifier(artifact_id)
        manifest = self.document(f"runs/{run_id}/artifacts.json", "artifacts")
        if manifest["run_id"] != run_id:
            raise DataError("Artifact manifest identity mismatch")
        entry = next(
            (
                item
                for item in manifest["artifacts"]
                if item["artifact_id"] == artifact_id
            ),
            None,
        )
        if not entry:
            raise DataError("Artifact unavailable", 404)
        if entry["sensitivity"] == "sensitive":
            raise DataError("Sensitive artifacts are not served", 403)
        # Resolve the path under its run root, not merely under CAS_DATA_DIR.
        lexical_base = self.root / "artifacts" / run_id
        base = self.path(f"artifacts/{run_id}")
        if base != lexical_base:
            raise DataError(
                "Artifact run directory may not redirect to another location", 400
            )
        path = self.path(f"artifacts/{run_id}/{entry['path']}")
        if not path.is_relative_to(base):
            raise DataError("Artifact escapes run root", 400)
        if path.stat().st_size > 8_000_000:
            raise DataError("Artifact exceeds download size limit", 413)
        content = path.read_bytes()
        if (
            len(content) != entry["size_bytes"]
            or hashlib.sha256(content).hexdigest() != entry["sha256"]
        ):
            raise DataError("Artifact integrity mismatch")
        return content, "application/octet-stream"


class Handler(BaseHTTPRequestHandler):
    def __init__(
        self, *args, store: Store, control=None, working_sessions=None, **kwargs
    ):
        self.store = store
        self.control = control
        self.working_sessions = working_sessions
        super().__init__(*args, **kwargs)

    def log_message(self, *_):
        pass

    def respond(self, content: bytes, media_type: str, status=200, attachment=None):
        self.send_response(status)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        )
        self.send_header("Cache-Control", "no-store")
        if attachment:
            self.send_header(
                "Content-Disposition", f'attachment; filename="{attachment}"'
            )
        self.end_headers()
        self.wfile.write(content)

    def json(self, document, status=200):
        self.respond(
            json.dumps(document, ensure_ascii=False, allow_nan=False).encode("utf-8"),
            "application/json; charset=utf-8",
            status,
        )

    def do_GET(self):
        try:
            host = self.headers.get("Host", "")
            valid_hosts = {
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            }
            if (
                host not in valid_hosts
                or self.headers.get("Origin", f"http://{host}") != f"http://{host}"
            ):
                raise DataError("Only same-origin loopback requests are accepted", 403)
            url = urlsplit(self.path)
            path = unquote(url.path)
            query = parse_qs(url.query)

            def number(key, default, maximum):
                try:
                    result = int(query.get(key, [str(default)])[0])
                except ValueError as error:
                    raise DataError("Invalid pagination", 400) from error
                if not (1 if key == "limit" else 0) <= result <= maximum:
                    raise DataError("Pagination outside allowed range", 400)
                return result

            if path.startswith("/api/working-sessions"):
                if self.working_sessions is None:
                    if path != "/api/working-sessions":
                        raise DataError("Working sessions disabled", 403)
                    self.json({"enabled": False})
                else:
                    self.json(self.working_sessions.get(path))
            elif path == "/api/control":
                self.json(self.control.info() if self.control else {"enabled": False})
            elif path == "/api/runs":
                self.json(
                    self.store.runs(
                        number("limit", 100, 500), number("offset", 0, 5000)
                    )
                )
            elif path == "/api/capabilities":
                self.json(self.store.document("capabilities/catalog.json", "catalog"))
            elif path.startswith("/api/runs/"):
                parts = path.strip("/").split("/")
                if len(parts) < 3:
                    raise DataError("Unknown endpoint", 404)
                run_id = identifier(parts[2])
                if len(parts) == 3:
                    self.json(self.store.detail(run_id))
                elif len(parts) == 4 and parts[3] == "events":
                    self.json(
                        self.store.events(
                            run_id,
                            number("after_seq", 0, 1_000_000),
                            number("limit", 200, 500),
                        )
                    )
                elif len(parts) == 5 and parts[3] == "artifacts":
                    artifact_id = identifier(parts[4])
                    content, media_type = self.store.artifact(run_id, artifact_id)
                    self.respond(
                        content, media_type, attachment=artifact_id + ".download"
                    )
                else:
                    raise DataError("Unknown endpoint", 404)
            elif path in {
                "/",
                "/index.html",
                "/styles.css",
                "/app.js",
                "/tasks.js",
                "/working-sessions.js",
            }:
                name = "index.html" if path == "/" else path[1:]
                media_type = {
                    "index.html": "text/html",
                    "styles.css": "text/css",
                    "app.js": "text/javascript",
                    "tasks.js": "text/javascript",
                    "working-sessions.js": "text/javascript",
                }[name]
                self.respond(asset_bytes(name), media_type + "; charset=utf-8")
            else:
                raise DataError("Unknown endpoint", 404)
        except DataError as error:
            self.json({"error": str(error)}, error.status)
        except (OSError, ValueError):
            self.json({"error": "Unavailable or corrupt local data"}, 422)

    def do_POST(self):
        try:
            if self.path.startswith("/api/working-sessions"):
                if self.working_sessions is None:
                    raise DataError("Working sessions disabled", 403)
                self.json(self.working_sessions.post(self), 200)
                return
            if self.control is None:
                raise DataError("Task control is disabled", 403)
            self.json(self.control.post(self), 200)
        except DataError as error:
            self.json({"error": str(error)}, error.status)
        except ValueError as error:
            self.json({"error": str(error)[:256]}, 409)
        except (OSError, RuntimeError, KeyError):
            self.json(
                {
                    "error": "Task operation rejected; refresh state and check consent/eligibility"
                },
                409,
            )


def create_server(
    data_dir: Path,
    host="127.0.0.1",
    port=8765,
    *,
    controller=None,
    working_sessions=None,
):
    if host != "127.0.0.1" or not 0 <= port <= 65535:
        raise ValueError("Console only supports 127.0.0.1")
    if controller is not None and working_sessions is not None:
        raise ValueError("Choose one console control mode")
    from agent_console.control import ControlBridge

    bridge = ControlBridge(controller) if controller is not None else None
    from agent_console.working_sessions import WorkingSessionBridge

    working = (
        WorkingSessionBridge(working_sessions) if working_sessions is not None else None
    )
    return ThreadingHTTPServer(
        (host, port),
        partial(
            Handler, store=Store(data_dir), control=bridge, working_sessions=working
        ),
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="cas-console")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument(
        "--root", type=Path, help="CAS umbrella required for working-session commands"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--enable-tasks",
        action="store_true",
        help="Enable coding-fixture task controls; requires separately installed runtime",
    )
    parser.add_argument(
        "--enable-working-sessions",
        action="store_true",
        help="Prepare/observe finite text tasks; run/login only in private local terminal",
    )
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("Port must be in 1..65535")
    controller = None
    if args.enable_tasks and args.enable_working_sessions:
        parser.error("Choose one console control mode")
    if args.enable_tasks:
        from agent_runtime.tasks.control import TaskControl

        controller = TaskControl(args.data_dir)
    if args.enable_working_sessions:
        from agent_runtime.tasks.working_sessions import WorkingSessions

        if args.root is None:
            parser.error("--enable-working-sessions requires --root")
        controller = WorkingSessions(args.data_dir, root=args.root)
    try:
        return serve(args, controller)
    finally:
        if controller is not None:
            controller.close()


def serve(args, controller):
    working = getattr(args, "enable_working_sessions", False)
    with create_server(
        args.data_dir,
        args.host,
        args.port,
        controller=None if working else controller,
        working_sessions=controller if working else None,
    ) as server:
        print(f"CAS console: http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0
