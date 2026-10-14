import hashlib
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from uuid import uuid4

from agent_console.server import asset_bytes, create_server


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.server = create_server(self.root, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.run_id = "00000000-0000-4000-8000-000000000001"
        self.directory = self.root / "runs" / self.run_id
        self.directory.mkdir(parents=True)
        fixture = Path(__file__).parent / "fixtures/run-task.json"
        self.record = json.loads(fixture.read_text())
        self.write("run.json", self.record)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def write(self, name, document):
        (self.directory / name).write_text(json.dumps(document), encoding="utf-8")

    def request(self, path, method="GET", headers=None):
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=3
        )
        try:
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_history_detail_and_static_are_independent(self):
        status, _, content = self.request("/api/runs")
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(content)["runs"]), 1)
        status, _, content = self.request(f"/api/runs/{self.run_id}")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(content)["run"]["run_id"], self.run_id)
        status, headers, content = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Understand every run", content)
        self.assertIn("Content-Security-Policy", headers)
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

    def test_untrusted_host_and_cross_origin_denied(self):
        for headers in (
            {"Host": "rebind.example:8765"},
            {"Origin": "https://untrusted.example"},
        ):
            status, _, _ = self.request("/api/runs", headers=headers)
            self.assertEqual(status, 403)

    def test_no_mutation_routes(self):
        before = (self.directory / "run.json").read_bytes()
        status, _, _ = self.request("/api/runs", method="POST")
        self.assertEqual(status, 501)
        self.assertEqual((self.directory / "run.json").read_bytes(), before)

    def test_bad_ids_traversal_and_pagination(self):
        for path in (
            "/api/runs/not-an-id",
            "/api/runs/%2e%2e",
            "/api/runs?limit=501",
            "/api/runs?offset=-1",
            "/api/runs?limit=0",
        ):
            status, _, _ = self.request(path)
            self.assertEqual(status, 400)

    def test_unknown_schema_and_corrupt_data_are_visible(self):
        self.record["schema_version"] = 2
        self.write("run.json", self.record)
        self.assertEqual(self.request(f"/api/runs/{self.run_id}")[0], 409)
        (self.directory / "run.json").write_text("invalid-json")
        self.assertEqual(self.request(f"/api/runs/{self.run_id}")[0], 422)
        _, _, content = self.request("/api/runs")
        self.assertTrue(json.loads(content)["warnings"])

    def test_partial_events_preserve_valid_prefix(self):
        event = {
            "schema_version": 1,
            "run_id": self.run_id,
            "seq": 1,
            "type": "sdk.message",
            "source": "sdk",
            "timestamp": "2026-10-14T00:00:00Z",
            "payload": {"text": "<script>bad()</script>"},
            "session_id": None,
            "parent_event_seq": None,
            "correlation_id": None,
            "redaction": {"applied": True, "fields": []},
        }
        (self.directory / "events.jsonl").write_text(
            json.dumps(event) + '\n{"partial":', encoding="utf-8"
        )
        status, _, content = self.request(f"/api/runs/{self.run_id}/events")
        data = json.loads(content)
        self.assertEqual(status, 200)
        self.assertEqual(len(data["events"]), 1)
        self.assertTrue(data["warnings"])

    def test_malformed_event_is_omitted_with_warning(self):
        (self.directory / "events.jsonl").write_text(
            json.dumps({"schema_version": 1, "run_id": self.run_id, "seq": 1}) + "\n",
            encoding="utf-8",
        )
        _, _, content = self.request(f"/api/runs/{self.run_id}/events")
        data = json.loads(content)
        self.assertEqual(data["events"], [])
        self.assertTrue(data["warnings"])

    def test_foreign_linked_record_is_not_returned(self):
        manifest = {"schema_version": 1, "run_id": str(uuid4()), "artifacts": []}
        self.write("artifacts.json", manifest)
        _, _, content = self.request(f"/api/runs/{self.run_id}")
        data = json.loads(content)
        self.assertIsNone(data["artifacts"])
        self.assertTrue(any("identity" in warning for warning in data["warnings"]))

    def test_artifacts_are_integrity_checked_downloads(self):
        artifact_id = str(uuid4())
        content = b"<script>untrusted()</script>"
        artifact = self.root / "artifacts" / self.run_id / artifact_id / "sample.html"
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(content)
        manifest = {
            "schema_version": 1,
            "run_id": self.run_id,
            "artifacts": [
                {
                    "artifact_id": artifact_id,
                    "path": f"{artifact_id}/sample.html",
                    "size_bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "media_type": "text/html",
                    "producer": "fixture",
                    "sensitivity": "normal",
                }
            ],
        }
        self.write("artifacts.json", manifest)
        path = f"/api/runs/{self.run_id}/artifacts/{artifact_id}"
        status, headers, actual = self.request(path)
        self.assertEqual(status, 200)
        self.assertEqual(actual, content)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertEqual(headers["Content-Type"], "application/octet-stream")
        artifact.write_bytes(b"tampered")
        self.assertEqual(self.request(path)[0], 422)
        manifest["artifacts"][0]["path"] = "../../secret"
        self.write("artifacts.json", manifest)
        self.assertIn(self.request(path)[0], (400, 422))

    def test_static_uses_safe_text_rendering(self):
        script = asset_bytes("app.js").decode("utf-8")
        self.assertNotIn("innerHTML", script)
        self.assertNotIn("eval(", script)
        self.assertIn("textContent", script)

    def test_remote_bind_rejected(self):
        with self.assertRaises(ValueError):
            create_server(self.root, host="0.0.0.0", port=0)
