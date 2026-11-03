"""Pipe-only real UI/Handler/store integration; only the test Node participant may spawn."""

import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_runtime.providers.claude.working_backend import DockerWorkingBackend
from agent_runtime.tasks.working_sessions import WorkingSessions
from agent_runtime.telemetry.recorder import atomic_json

from agent_console.server import Handler
from agent_console.working_sessions import WorkingSessionBridge

ROOT = Path(__file__).resolve().parent
PROJECT = Path(sys.modules["agent_console.server"].__file__).resolve().parents[4]
_node = os.environ.get("CAS_NODE_EXE") or shutil.which("node")
NODE = Path(_node) if _node else None


class ControlledBackend(DockerWorkingBackend):
    def approval(self, record, digest, approved=False):
        # Deliberately incompatible with the strict production approval contract.
        return super().approval(record, digest, approved) | {"test_backend_only": True}

    def __init__(self, mode, cleanup_failure=False):
        self.mode = mode
        self.cleanup_failure = cleanup_failure
        self.runs = 0
        self.queries = 0
        for name in [
            "first_done",
            "second_started",
            "second_done",
            "cleanup_entered",
            "release_second",
            "release_work",
            "release_return",
            "release_cleanup",
        ]:
            setattr(self, name, threading.Event())
        self.trace = []

    def report(self, d, index):
        stage = ("first", "second")[index]
        return {
            "scope": "cas-working-task-v1",
            "stage": stage,
            "run_id": d["tasks"][index]["run_id"],
            "result": "PASS",
            "query_count": 1,
            "native_success": True,
            "text": ("First", "Second")[index] + " offline result",
            "session_hash": hashlib.sha256(
                (d["session_id"] + stage).encode()
            ).hexdigest(),
            "tree_empty": True,
            "auth_profile_shared": True,
            "context_isolation": "NOT_PROVED",
            "failure_code": None,
        }

    def wait(self, event):
        if not event.wait(5):
            raise RuntimeError("TEST_BARRIER_TIMEOUT")

    def run(self, bundle, d, approval):
        assert approval != DockerWorkingBackend().approval(d, d["plan_hash"], True)
        self.verify(bundle, d)
        name = "agent_runtime.providers.claude._wire_approval_" + d[
            "session_id"
        ].replace("-", "")
        definition = importlib.util.spec_from_file_location(
            name, Path(bundle) / "__init__.py", submodule_search_locations=[str(bundle)]
        )
        module = importlib.util.module_from_spec(definition)
        sys.modules[name] = module
        old_bytecode = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        try:
            definition.loader.exec_module(module)
            controller = __import__(name + ".controller", fromlist=["gates"])
            try:
                controller.gates(approval)
            except controller.Failure as failure:
                assert str(failure) == "fresh-specific-owner-grant-required"
            else:
                raise AssertionError("SYNTHETIC_APPROVAL_ACCEPTED_BY_PRODUCTION")
            assert not (Path(bundle) / "attempt.claim.json").exists()
            assert not (Path(bundle) / "runtime-evidence").exists()
        finally:
            sys.dont_write_bytecode = old_bytecode
            for key in list(sys.modules):
                if key == name or key.startswith(name + "."):
                    sys.modules.pop(key, None)
        self.runs += 1
        self.bundle = Path(bundle)
        self.d = d
        self.queries += 1
        self.trace.append("first_completed")
        stages = [self.report(d, 0)]

        def progress():
            atomic_json(
                self.bundle / "progress.json",
                {
                    "session_id": d["session_id"],
                    "attempt": d["attempt_id"],
                    "status": "RUNNING",
                    "stages": {
                        s: r for s, r in zip(("first", "second"), stages, strict=False)
                    },
                },
            )

        progress()
        self.first_done.set()
        self.wait(self.release_second)
        cancelled = (self.bundle / "cancel.request.json").exists()
        if not cancelled:
            self.queries += 1
            self.trace.append("second_started")
            self.second_started.set()
            self.wait(self.release_work)
            cancelled = (self.bundle / "cancel.request.json").exists()
            if not cancelled:
                stages.append(self.report(d, 1))
                self.trace.append("second_completed")
                progress()
        self.second_done.set()
        self.wait(self.release_return)
        self.cleanup_entered.set()
        self.wait(self.release_cleanup)
        self.trace.append(
            "cleanup_unconfirmed" if self.cleanup_failure else "cleanup_confirmed"
        )
        complete = len(stages) == 2
        return {
            "completed": complete,
            "cleanup_confirmed": not self.cleanup_failure,
            "cancelled": cancelled,
            "stages": stages,
            "code": None if complete else "WORKING_SESSION_NOT_COMPLETED",
        }


class Harness:
    def __init__(self, root):
        self.root = root
        self.cases = []
        self.http_trace = []
        self.thread = None
        self.bridge = None

    def setup(self, value):
        assert self.thread is None or not self.thread.is_alive()
        self.backend = ControlledBackend(
            value["mode"], value.get("cleanupFailure", False)
        )
        self.owner = WorkingSessions(
            self.root / value["mode"], backend=self.backend, root=PROJECT
        )
        self.controller = WorkingSessions(
            self.root / value["mode"], backend=self.backend, root=PROJECT
        )
        self.bridge = WorkingSessionBridge(self.controller)
        self.d = self.owner.create("Synthetic offline " + value["mode"])
        if not value.get("draft"):
            for i in range(2):
                self.d = self.owner.add(
                    self.d["session_id"],
                    title=str(i),
                    prompt="Synthetic nonsensitive task",
                )
            self.d = self.owner.prepare(self.d["session_id"])
        self.thread = None
        return {"session_id": self.d["session_id"]}

    def http(self, value):
        body = value.get("body", "").encode()
        headers = {"Host": "127.0.0.1:8765", **value.get("headers", {})}
        if value["method"] == "POST":
            headers.setdefault("Origin", "http://127.0.0.1:8765")
            headers.setdefault("Content-Length", str(len(body)))
        outputs = []
        handler = types.SimpleNamespace(
            path=value["path"],
            headers=headers,
            server=types.SimpleNamespace(server_port=8765),
            working_sessions=self.bridge,
            control=None,
            rfile=io.BytesIO(body),
            connection=types.SimpleNamespace(settimeout=lambda _: None),
        )
        handler.respond = lambda content, media_type, status=200: outputs.append(
            {
                "status": status,
                "body": json.loads(content)
                if media_type.startswith("application/json")
                else content.decode("utf-8"),
            }
        )
        handler.json = types.MethodType(Handler.json, handler)
        (Handler.do_POST if value["method"] == "POST" else Handler.do_GET)(handler)
        assert len(outputs) == 1
        self.http_trace.append(
            {
                "method": value["method"],
                "path": value["path"],
                "status": outputs[0]["status"],
            }
        )
        return outputs[0]

    def start(self):
        approval = (
            self.owner.folder(self.d["session_id"])
            / "synthetic-only-test-approval.json"
        )
        atomic_json(approval, self.backend.approval(self.d, self.d["plan_hash"], True))
        self.thread = threading.Thread(
            target=lambda: self.owner.run(
                self.d["session_id"], approval, allow_live=True
            )
        )
        self.thread.start()
        assert self.backend.first_done.wait(5)
        return True

    def snapshot(self):
        d = self.controller.get(self.d["session_id"])
        marker = self.controller.bundle(self.d) / "cancel.request.json"
        intent = None
        if marker.exists():
            intent = json.loads(marker.read_text(encoding="utf-8")) == {
                "session_id": d["session_id"],
                "attempt": d["attempt_id"],
                "manifest_sha256": d["plan_hash"],
            }
        return {
            "status": d["status"],
            "cleanup": d["cleanup"],
            "results": len(d["results"]),
            "synthetic_queries": self.backend.queries,
            "backend_runs": self.backend.runs,
            "claim_exists": self.owner._claim(d).exists(),
            "intent_matches_plan": intent,
        }

    def command(self, value):
        op = value["op"]
        if op == "setup":
            return self.setup(value)
        if op == "http":
            return self.http(value)
        if op == "start":
            return self.start()
        if op == "start_second":
            self.backend.release_second.set()
            assert self.backend.second_started.wait(5)
            return True
        if op == "complete_second":
            self.backend.release_work.set()
            assert self.backend.second_done.wait(5)
            return True
        if op == "enter_cleanup":
            self.backend.release_second.set()
            self.backend.release_work.set()
            self.backend.release_return.set()
            assert self.backend.cleanup_entered.wait(5)
            return True
        if op == "settle":
            self.backend.release_second.set()
            self.backend.release_work.set()
            self.backend.release_return.set()
            self.backend.release_cleanup.set()
            self.thread.join(5)
            assert not self.thread.is_alive()
            return True
        if op == "snapshot":
            return self.snapshot()
        if op == "reopen":
            self.controller = WorkingSessions(
                self.owner.data_dir, backend=self.backend, root=PROJECT
            )
            self.bridge = WorkingSessionBridge(self.controller)
            return True
        if op == "guard_checks":
            before = self.snapshot()
            path = "/api/working-sessions/" + self.d["session_id"] + "/cancel"
            value = {
                "method": "POST",
                "path": path,
                "body": json.dumps({"plan_hash": self.d["plan_hash"]}),
                "headers": {
                    "Content-Type": "application/json",
                    "X-CAS-CSRF": self.bridge.token,
                },
            }
            codes = []
            for key, bad in [
                ("Origin", "https://invalid.example"),
                ("Host", "invalid.example:8765"),
                ("X-CAS-CSRF", "invalid"),
            ]:
                request = dict(value, headers={**value["headers"], key: bad})
                codes.append(self.http(request)["status"])
            request = dict(value, body=json.dumps({"plan_hash": "0" * 64}))
            codes.append(self.http(request)["status"])
            assert codes == [409] * 4 and self.snapshot() == before
            return {"rejected": len(codes), "state_unchanged": True}
        if op == "try_replay":
            try:
                self.owner.run(
                    self.d["session_id"],
                    self.owner.folder(self.d["session_id"])
                    / "synthetic-only-test-approval.json",
                    allow_live=True,
                )
            except (ValueError, PermissionError):
                return {"blocked": True}
            raise AssertionError("REPLAY_ALLOWED")
        if op == "record_case":
            self.cases.append(
                {
                    "name": value["caseName"],
                    "state": self.snapshot(),
                    "trace": self.backend.trace.copy(),
                }
            )
            return True
        if op == "finish":
            return {"finished": True}
        if op == "failed":
            raise AssertionError(value["message"])
        raise ValueError("UNKNOWN_TEST_COMMAND")


def main():
    if NODE is None or not NODE.is_file():
        raise unittest.SkipTest("Installed Node.js required; no auto-install")
    with tempfile.TemporaryDirectory(dir=os.environ.get("CAS_TEST_TMP")) as directory:
        h = Harness(Path(directory))
        page = h.http({"method": "GET", "path": "/"})
        asset = h.http({"method": "GET", "path": "/working-sessions.js"})
        assert (
            page["status"] == asset["status"] == 200
            and "/working-sessions.js" in page["body"]
        )
        ui = Path(directory) / "actual-working-sessions.js"
        ui.write_bytes(asset["body"].encode("utf-8"))
        # The one subprocess is a known Node.js test participant. It uses only stdin/stdout IPC.
        process = subprocess.Popen(
            [str(NODE), str(ROOT / "working_sessions_cancel_wire.cjs"), str(ui)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        error = None
        expired = threading.Event()

        def expire():
            expired.set()
            if process.poll() is None:
                process.kill()

        watchdog = threading.Timer(30, expire)
        watchdog.start()
        try:
            with (
                patch(
                    "subprocess.Popen", side_effect=AssertionError("NO_NATIVE_PROCESS")
                ),
                patch("socket.socket", side_effect=AssertionError("NO_SOCKET")),
                patch("sys.stdin.isatty", return_value=True),
                patch("sys.stdout.isatty", return_value=True),
                patch("sys.stderr.isatty", return_value=True),
            ):
                for line in process.stdout:
                    request = json.loads(line)
                    try:
                        value = h.command(request)
                        response = {"id": request["id"], "value": value}
                    except (
                        AssertionError,
                        ValueError,
                        RuntimeError,
                        OSError,
                        TypeError,
                        KeyError,
                    ) as failure:
                        error = repr(failure)
                        response = {"id": request["id"], "error": error}
                    process.stdin.write(json.dumps(response) + "\n")
                    process.stdin.flush()
                    if request["op"] in {"finish", "failed"}:
                        break
            process.wait(timeout=5)
        finally:
            watchdog.cancel()
            watchdog.join(2)
            if h.thread is not None and h.thread.is_alive():
                for name in [
                    "release_second",
                    "release_work",
                    "release_return",
                    "release_cleanup",
                ]:
                    getattr(h.backend, name).set()
                h.thread.join(5)
            if process.poll() is None:
                process.kill()
                process.wait(timeout=2)
        stderr = process.stderr.read()
        for stream in [process.stdin, process.stdout, process.stderr]:
            stream.close()
        report = {
            "result": "PASS"
            if process.returncode == 0 and error is None and not expired.is_set()
            else "FAIL",
            "cases": h.cases,
            "http_trace": h.http_trace,
            "node_rc": process.returncode,
            "error": error,
            "node_stderr": stderr,
            "whole_run_deadline_seconds": 30,
            "deadline_expired": expired.is_set(),
            "real_http_handler": True,
            "real_product_store": True,
            "actual_ui_source": True,
            "ui_asset_sha256": hashlib.sha256(ui.read_bytes()).hexdigest(),
            "transport": "stdin-stdout-only-no-server",
            "backend": "controlled synthetic no SDK/native",
            "server": "NOT_RUN",
            "docker": "NOT_RUN",
            "login": "NOT_RUN",
            "provider": "NOT_RUN",
        }
        output = os.environ.get("CAS_PRODUCT_WIRE_EVIDENCE")
        if output:
            destination = Path(output)
            destination.mkdir(parents=True, exist_ok=True)
            (destination / "crosslayer-result.json").write_text(
                json.dumps(report, indent=2) + "\n"
            )
        print(
            json.dumps(
                {
                    "result": report["result"],
                    "cases": len(h.cases),
                    "http_requests": len(h.http_trace),
                    "error": error,
                    "node_stderr": stderr,
                },
                indent=2,
            )
        )
        return 0 if report["result"] == "PASS" else 1


class ProductConsoleCancellationTests(unittest.TestCase):
    def test_ui_handler_runtime_cancel_history_and_reopen_without_server(self):
        self.assertEqual(main(), 0)


if __name__ == "__main__":
    unittest.main()
