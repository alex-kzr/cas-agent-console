"""Direct handler/bridge tests: no HTTP server, sockets, credentials or model."""

import io
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from agent_console.server import Handler
from agent_console.working_sessions import WorkingSessionBridge
from agent_runtime.tasks.working_sessions import WorkingSessions
from agent_runtime.providers.claude.working_backend import LEGACY_PRIVATE
from agent_runtime.telemetry.recorder import RunLock


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get("CAS_TEST_TMP"))
        self.addCleanup(self.temp.cleanup)
        self.store = WorkingSessions(self.temp.name, root=self.temp.name)
        self.bridge = WorkingSessionBridge(self.store)

    def handler(self, path, value, headers=None):
        raw = json.dumps(value).encode()
        base = {
            "Host": "127.0.0.1:8765",
            "Origin": "http://127.0.0.1:8765",
            "Content-Type": "application/json",
            "Content-Length": str(len(raw)),
            "X-CAS-CSRF": self.bridge.token,
        }
        base.update(headers or {})
        return types.SimpleNamespace(
            path=path,
            headers=base,
            rfile=io.BytesIO(raw),
            connection=types.SimpleNamespace(settimeout=lambda n: None),
            server=types.SimpleNamespace(server_port=8765),
        )

    def test_prepare_history_scope_and_end_no_run_route(self):
        d = self.bridge.post(
            self.handler("/api/working-sessions", {"title": "Product work"})
        )
        sid = d["session_id"]
        base = "/api/working-sessions/" + sid
        for i in range(2):
            self.bridge.post(
                self.handler(
                    base + "/tasks", {"title": str(i), "prompt": "A synthetic task"}
                )
            )
        d = self.bridge.post(self.handler(base + "/prepare", {}))
        self.assertEqual(d["status"], "PREPARED")
        self.assertFalse(
            self.bridge.get(base + "/scope")["approval_template"]["approved"]
        )
        for action in ["run", "login", "approve", "restart"]:
            with self.assertRaises(ValueError):
                self.bridge.post(self.handler(base + "/" + action, {}))
        ended = self.bridge.post(
            self.handler(base + "/end", {"plan_hash": d["plan_hash"]})
        )
        self.assertEqual(ended["status"], "CLOSED")
        self.assertEqual(
            self.bridge.get("/api/working-sessions")["sessions"][0]["status"], "CLOSED"
        )

    def test_local_owner_can_start_once_and_failed_start_is_visible(self):
        source = Path(self.temp.name) / 'synthetic-auth'
        source.write_text('synthetic')
        with patch.dict(os.environ, {'CAS_LOCAL_OWNER_AUTH_FILE': str(source)}):
            self.assertEqual(self.bridge.info()['mode'], 'local-owner-console')
            d = self.bridge.post(self.handler('/api/working-sessions', {'title': 'Synthetic'}))
            base = '/api/working-sessions/' + d['session_id']
            self.bridge.post(self.handler(base + '/tasks', {'title': 'One', 'prompt': 'Synthetic task'}))
            d = self.bridge.post(self.handler(base + '/prepare', {}))
            process = types.SimpleNamespace(poll=lambda: None)
            with patch('agent_console.working_sessions.subprocess.Popen', return_value=process) as spawn:
                reply = self.bridge.post(self.handler(base + '/run', {'plan_hash': d['plan_hash']}))
                self.assertTrue(reply['accepted'])
                self.assertEqual(spawn.call_count, 1)
                self.assertIn('--allow-live', spawn.call_args.args[0])
                self.assertNotIn(str(source), spawn.call_args.args[0])
                with self.assertRaises(ValueError):
                    self.bridge.post(self.handler(base + '/run', {'plan_hash': d['plan_hash']}))
                self.assertEqual(spawn.call_count, 1)
            process.poll = lambda: 1
            self.assertIn('launch_error', self.bridge.get(base))

    def test_stale_plan_cannot_start(self):
        source = Path(self.temp.name) / 'synthetic-auth'
        source.write_text('synthetic')
        with patch.dict(os.environ, {'CAS_LOCAL_OWNER_AUTH_FILE': str(source)}):
            d = self.bridge.post(self.handler('/api/working-sessions', {'title': 'Synthetic'}))
            base = '/api/working-sessions/' + d['session_id']
            self.bridge.post(self.handler(base + '/tasks', {'title': 'One', 'prompt': 'Synthetic task'}))
            self.bridge.post(self.handler(base + '/prepare', {}))
            with patch('agent_console.working_sessions.subprocess.Popen') as spawn:
                with self.assertRaises(ValueError):
                    self.bridge.post(self.handler(base + '/run', {'plan_hash': '0' * 64}))
                spawn.assert_not_called()

    def test_legacy_sensitive_plan_is_explained_without_launch_or_claim(self):
        source = Path(self.temp.name) / 'synthetic-auth'
        source.write_text('synthetic')
        with patch.dict(os.environ, {'CAS_LOCAL_OWNER_AUTH_FILE': str(source)}):
            with patch('agent_runtime.tasks.working_sessions.PRIVATE', LEGACY_PRIVATE):
                d = self.bridge.post(self.handler('/api/working-sessions', {'title': 'Synthetic'}))
                base = '/api/working-sessions/' + d['session_id']
                self.bridge.post(self.handler(base + '/tasks', {'title': 'One', 'prompt': 'accessToken: SYNTHETIC_PRIVATE'}))
                d = self.bridge.post(self.handler(base + '/prepare', {}))
            with patch('agent_console.working_sessions.subprocess.Popen') as spawn:
                reply = self.bridge.post(self.handler(base + '/run', {'plan_hash': d['plan_hash']}))
                self.assertEqual(reply['reason'], 'WORKING_SESSION_INPUT_REQUIRES_NEW_TASK')
                self.assertFalse(reply['accepted'])
                spawn.assert_not_called()
                self.assertFalse(self.store._claim(d).exists())

    def test_second_session_waits_while_first_owner_is_running(self):
        source = Path(self.temp.name) / 'synthetic-auth'
        source.write_text('synthetic')
        with patch.dict(os.environ, {'CAS_LOCAL_OWNER_AUTH_FILE': str(source)}):
            prepared = []
            for title in ('first', 'second'):
                d = self.bridge.post(self.handler('/api/working-sessions', {'title': title}))
                base = '/api/working-sessions/' + d['session_id']
                self.bridge.post(self.handler(base + '/tasks', {'title': title, 'prompt': 'Synthetic task'}))
                prepared.append((base, self.bridge.post(self.handler(base + '/prepare', {}))))
            process = types.SimpleNamespace(poll=lambda: None)
            with patch('agent_console.working_sessions.subprocess.Popen', return_value=process) as spawn:
                first, second = prepared
                self.assertTrue(self.bridge.post(self.handler(first[0] + '/run', {'plan_hash': first[1]['plan_hash']}))['accepted'])
                reply = self.bridge.post(self.handler(second[0] + '/run', {'plan_hash': second[1]['plan_hash']}))
                self.assertEqual((reply['accepted'], reply['reason']), (False, 'WORKING_SESSION_BUSY'))
                self.assertEqual(spawn.call_count, 1)
                self.assertFalse(self.store._claim(second[1]).exists())

    def test_running_external_owner_also_blocks_start_without_consuming(self):
        source = Path(self.temp.name) / 'synthetic-auth'
        source.write_text('synthetic')
        with patch.dict(os.environ, {'CAS_LOCAL_OWNER_AUTH_FILE': str(source)}):
            prepared = []
            for title in ('first', 'second'):
                d = self.bridge.post(self.handler('/api/working-sessions', {'title': title}))
                base = '/api/working-sessions/' + d['session_id']
                self.bridge.post(self.handler(base + '/tasks', {'title': title, 'prompt': 'Synthetic task'}))
                prepared.append((base, self.bridge.post(self.handler(base + '/prepare', {}))))
            first, second = prepared
            record = self.store.load(first[1]['session_id'])
            record.update(status='RUNNING', cleanup='PENDING')
            self.store.save(record)
            self.store._claim(record).write_text('synthetic consumed', encoding='utf-8')
            with RunLock(self.store.directory / '.active'):
                with patch('agent_console.working_sessions.subprocess.Popen') as spawn:
                    reply = self.bridge.post(self.handler(second[0] + '/run', {'plan_hash': second[1]['plan_hash']}))
                    self.assertEqual((reply['accepted'], reply['reason']), (False, 'WORKING_SESSION_BUSY'))
                    spawn.assert_not_called()
                    self.assertFalse(self.store._claim(second[1]).exists())

    def test_origin_csrf_encoding_lengths_duplicates_and_private_errors(self):
        for headers in [
            {"Host": "evil:8765"},
            {"Origin": "https://evil"},
            {"X-CAS-CSRF": "bad"},
            {"Transfer-Encoding": "chunked"},
            {"Content-Type": "text/plain"},
            {"Content-Length": "999999"},
            {"Content-Length": "password=SYNTHETIC_PRIVATE"},
        ]:
            with self.assertRaises(ValueError) as caught:
                self.bridge.post(
                    self.handler("/api/working-sessions", {"title": "x"}, headers)
                )
            self.assertEqual(str(caught.exception), "WORKING_SESSION_ACTION_REJECTED")
        h = self.handler("/api/working-sessions", {"title": "x"})
        raw = b'{"title":"a","title":"b"}'
        h.rfile = io.BytesIO(raw)
        h.headers["Content-Length"] = str(len(raw))
        with self.assertRaises(ValueError):
            self.bridge.post(h)

    def test_server_disabled_and_separate_prefix_do_not_touch_legacy_control(self):
        outputs = []
        fake = types.SimpleNamespace(
            path="/api/working-sessions",
            working_sessions=None,
            control=types.SimpleNamespace(
                post=lambda h: (_ for _ in ()).throw(AssertionError("legacy touched"))
            ),
            json=lambda d, status=200: outputs.append((status, d)),
        )
        Handler.do_POST(fake)
        self.assertEqual(outputs[0][0], 403)
        outputs.clear()
        fake.working_sessions = self.bridge
        h = self.handler("/api/working-sessions", {"title": "New"})
        fake.__dict__.update(h.__dict__)
        Handler.do_POST(fake)
        self.assertEqual(outputs[0][0], 200)
        self.assertEqual(outputs[0][1]["status"], "DRAFT")


if __name__ == "__main__":
    with (
        patch("socket.socket", side_effect=AssertionError("NO_SOCKET")),
        patch("subprocess.Popen", side_effect=AssertionError("NO_PROCESS")),
    ):
        unittest.main()
