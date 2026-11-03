"""Forced kernel record-lock ordering; no server/browser/SDK/Docker execution."""

import errno
import importlib.util
import os
import site
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_runtime.telemetry.recorder import RunLock, atomic_json
from test_working_sessions_crosslayer import PROJECT, ControlledBackend

HERE = Path(__file__).resolve().parent
if os.environ.get("CAS_RACE_SOURCE"):
    spec = importlib.util.spec_from_file_location(
        "cancel_candidate", Path(os.environ["CAS_RACE_SOURCE"])
    )
    candidate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(candidate)
else:
    from agent_runtime.tasks import working_sessions as candidate
WorkingSessions = candidate.WorkingSessions


class RecordRaceTests(unittest.TestCase):
    def setup_pair(self, folder, mode):
        release = threading.Event()

        class Backend(ControlledBackend):
            def run(self, bundle, d, approval):
                self.runs += 1
                self.queries = 1
                first = self.report(d, 0)
                atomic_json(
                    Path(bundle) / "progress.json",
                    {
                        "session_id": d["session_id"],
                        "attempt": d["attempt_id"],
                        "status": "RUNNING",
                        "stages": {"first": first},
                    },
                )
                self.second_started.set()
                if not release.wait(5):
                    raise AssertionError("TEST_RELEASE_TIMEOUT")
                cancelled = (Path(bundle) / "cancel.request.json").exists()
                stages = [first] if mode != "complete" else [first, self.report(d, 1)]
                return {
                    "completed": mode == "complete",
                    "cleanup_confirmed": mode != "unclean",
                    "cancelled": cancelled,
                    "stages": stages,
                    "code": None
                    if mode == "complete"
                    else "WORKING_SESSION_NOT_COMPLETED",
                }

        backend = Backend("forced-order")
        owner = WorkingSessions(Path(folder), backend=backend, root=PROJECT)
        peer = WorkingSessions(Path(folder), backend=backend, root=PROJECT)
        d = owner.create("SYNTHETIC forced lock ordering")
        for i in (1, 2):
            d = owner.add(d["session_id"], title=str(i), prompt="Synthetic fixed task")
        d = owner.prepare(d["session_id"])
        approval = owner.folder(d["session_id"]) / "synthetic-only.json"
        atomic_json(approval, backend.approval(d, d["plan_hash"], True))
        return owner, peer, backend, d, approval, release

    def ordering(self, cancel_first, mode="cancel"):
        with tempfile.TemporaryDirectory(dir=HERE) as folder:
            owner, peer, backend, d, approval, release = self.setup_pair(folder, mode)
            locked, unlock, contended = (threading.Event() for _ in range(3))
            errors = []
            original_enter = RunLock.__enter__
            holder = peer if cancel_first else owner
            original_save = holder.save

            def held_save(record):
                wanted = (
                    record["status"] == "CANCEL_REQUESTED"
                    if cancel_first
                    else record["status"] in candidate.TERMINAL
                )
                if wanted:
                    locked.set()
                    if not unlock.wait(5):
                        raise AssertionError("TEST_UNLOCK_TIMEOUT")
                return original_save(record)

            def observed_enter(lock):
                try:
                    return original_enter(lock)
                except RuntimeError:
                    if lock.data_dir.name == ".records":
                        contended.set()
                    raise

            def capture(fn):
                try:
                    fn()
                except BaseException as e:  # noqa: BLE001 - test worker exception capture
                    errors.append(repr(e))

            with (
                patch.object(holder, "save", side_effect=held_save),
                patch.object(RunLock, "__enter__", observed_enter),
                patch("sys.stdin.isatty", return_value=True),
                patch("sys.stdout.isatty", return_value=True),
                patch("sys.stderr.isatty", return_value=True),
                patch("socket.socket", side_effect=AssertionError("NO_SOCKET")),
                patch("subprocess.Popen", side_effect=AssertionError("NO_NATIVE")),
            ):
                work = threading.Thread(
                    target=lambda: capture(
                        lambda: owner.run(d["session_id"], approval, allow_live=True)
                    )
                )
                intent = threading.Thread(
                    target=lambda: capture(
                        lambda: peer.request(d["session_id"], d["plan_hash"])
                    )
                )
                work.start()
                try:
                    self.assertTrue(backend.second_started.wait(5))
                    if cancel_first:
                        intent.start()
                        self.assertTrue(locked.wait(5))
                        release.set()
                    else:
                        release.set()
                        self.assertTrue(locked.wait(5))
                        intent.start()
                    self.assertTrue(
                        contended.wait(5), "must exercise actual kernel contention"
                    )
                finally:
                    unlock.set()
                    release.set()
                    work.join(5)
                    if intent.ident:
                        intent.join(5)
                self.assertFalse(work.is_alive())
                self.assertFalse(intent.is_alive())
            self.assertEqual(errors, [])
            final = peer.get(d["session_id"])
            expected = (
                "COMPLETED"
                if mode == "complete"
                else "INTERRUPTED"
                if mode == "unclean"
                else "CANCELLED"
                if cancel_first
                else "FAILED"
            )
            self.assertEqual(final["status"], expected)
            self.assertEqual(
                final["cleanup"], "UNCONFIRMED" if mode == "unclean" else "CONFIRMED"
            )
            self.assertEqual(final["results"][0]["text"], "First offline result")
            self.assertEqual(
                (owner.bundle(d) / "cancel.request.json").exists(), cancel_first
            )
            peer.request(d["session_id"], d["plan_hash"], end=True)
            stale = dict(
                d,
                status="FAILED",
                results=[],
                cleanup="UNCONFIRMED",
                code="WORKING_SESSION_NOT_COMPLETED",
            )
            self.assertEqual(
                owner.commit_terminal(d["session_id"], stale)["status"], expected
            )
            self.assertEqual(peer.get(d["session_id"])["results"], final["results"])
            self.assertEqual(backend.runs, 1)

    def test_cancel_holds_lock_before_terminal(self):
        self.ordering(True)

    def test_terminal_holds_lock_before_cancel(self):
        self.ordering(False)

    def test_completed_outcome_wins_late_accepted_intent_keeps_marker(self):
        self.ordering(True, "complete")

    def test_unclean_outcome_not_masked_by_intent(self):
        self.ordering(True, "unclean")

    def test_timeout_and_non_contention_failure_are_not_swallowed(self):
        with tempfile.TemporaryDirectory(dir=HERE) as folder:
            store = WorkingSessions(Path(folder), root=PROJECT)

            def busy(_):
                raise RuntimeError(
                    "Another CAS execution owns this data directory"
                ) from OSError(errno.EACCES, "busy")

            with (
                patch.object(RunLock, "__enter__", busy),
                patch.object(candidate.time, "monotonic", side_effect=[0, 6]),
                self.assertRaisesRegex(RuntimeError, "RECORD_LOCK_TIMEOUT"),
                store.guard(),
            ):
                self.fail("cannot acquire")
            with (
                patch.object(
                    RunLock, "__enter__", side_effect=RuntimeError("UNRELATED")
                ),
                self.assertRaisesRegex(RuntimeError, "UNRELATED"),
                store.guard(),
            ):
                self.fail("cannot acquire")

            def io_error(_):
                raise RuntimeError(
                    "Another CAS execution owns this data directory"
                ) from OSError(errno.EIO, "not contention")

            with (
                patch.object(RunLock, "__enter__", io_error),
                self.assertRaisesRegex(RuntimeError, "Another CAS"),
                store.guard(),
            ):
                self.fail("cannot acquire")

    def test_separate_python_process_cancel_lock_and_owner_terminal_commit(self):
        with tempfile.TemporaryDirectory(dir=HERE) as folder:
            root = Path(folder)
            owner, peer, backend, d, approval, release = self.setup_pair(root, "cancel")
            atomic_json(
                root / "peer-plan.json",
                {
                    "session_id": d["session_id"],
                    "plan_hash": d["plan_hash"],
                    "project_root": str(PROJECT),
                    # Under a bootstrapped -S interpreter, site.getsitepackages() names the
                    # base installation; the active venv packages are only on sys.path.
                    "site_paths": list(
                        dict.fromkeys(
                            str(Path(p).resolve())
                            for p in [*sys.path, *site.getsitepackages()]
                            if p
                            and Path(p).is_dir()
                            and Path(p).name in {"site-packages", "dist-packages"}
                        )
                    ),
                },
            )
            errors = []

            def run():
                try:
                    owner.run(d["session_id"], approval, allow_live=True)
                except BaseException as exc:  # noqa: BLE001 - offline participant diagnostics
                    errors.append(repr(exc))

            work = threading.Thread(target=run)
            child = None
            busy = threading.Event()
            original_enter = RunLock.__enter__

            def observe(lock):
                try:
                    return original_enter(lock)
                except RuntimeError:
                    if lock.data_dir.name == ".records":
                        busy.set()
                    raise

            with (
                patch("sys.stdin.isatty", return_value=True),
                patch("sys.stdout.isatty", return_value=True),
                patch("sys.stderr.isatty", return_value=True),
                patch.object(RunLock, "__enter__", observe),
            ):
                work.start()
                try:
                    self.assertTrue(backend.second_started.wait(5))
                    child = subprocess.Popen(
                        [
                            sys._base_executable,
                            "-I",
                            "-B",
                            str(HERE / "working_session_lock_peer.py"),
                            str(root),
                            str(Path(candidate.__file__).resolve()),
                        ],
                        cwd=HERE,
                        env={
                            k: os.environ[k] for k in ("SystemRoot",) if k in os.environ
                        },
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    deadline = time.monotonic() + 3
                    while (
                        not (root / "peer-ready").exists()
                        and time.monotonic() < deadline
                    ):
                        threading.Event().wait(0.01)
                    if not (root / "peer-ready").exists():
                        detail = "peer still running"
                        if child.poll() is not None:
                            out, err = child.communicate(timeout=2)
                            detail = f"rc={child.returncode} stdout={out!r} stderr={err[-2000:]!r}"
                        self.fail(f"peer did not acquire the lock: {detail}")
                    release.set()
                    self.assertTrue(busy.wait(2))
                    (root / "peer-release").write_text("release")
                    stdout, stderr = child.communicate(timeout=5)
                    self.assertEqual(child.returncode, 0, stderr)
                    self.assertEqual(stdout.strip(), "OFFLINE_PEER_DONE")
                finally:
                    release.set()
                    (root / "peer-release").write_text("release")
                    if child and child.poll() is None:
                        child.kill()
                        child.communicate(timeout=2)
                    work.join(5)
            self.assertFalse(work.is_alive())
            self.assertEqual(errors, [])
            final = peer.get(d["session_id"])
            self.assertEqual(final["status"], "CANCELLED")
            self.assertEqual(final["cleanup"], "CONFIRMED")
            self.assertEqual(len(final["results"]), 1)
            self.assertTrue((owner.bundle(d) / "cancel.request.json").exists())
            stale = dict(
                d, attempt_id="00000000-0000-0000-0000-000000000000", status="FAILED"
            )
            with self.assertRaisesRegex(ValueError, "STALE_WORKING_SESSION_TERMINAL"):
                owner.commit_terminal(d["session_id"], stale)
            self.assertEqual(peer.get(d["session_id"])["status"], "CANCELLED")


if __name__ == "__main__":
    unittest.main()
