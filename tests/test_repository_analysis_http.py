"""Actual loopback HTTP, source validation and export; no native/provider adapter."""

import http.client
import io
import json
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

from agent_console.repository_analysis import create_analysis_server
from agent_console.server import create_server
from agent_runtime.tasks.repository_analysis import AnalysisControl


class AnalysisHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.control = AnalysisControl(Path(self.temp.name) / "data")
        self.addCleanup(self.control.close)
        self.server = create_analysis_server(self.control, 0)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.thread.join)
        self.addCleanup(self.server.shutdown)
        self.host = f"127.0.0.1:{self.server.server_port}"
        status, body, _ = self.request("GET", "/api/analysis")
        self.assertEqual(status, 200)
        self.headers = {
            "Content-Type": "application/json",
            "Origin": "http://" + self.host,
            "X-CAS-CSRF": json.loads(body)["csrf"],
        }

    def request(self, method, path, value=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request(
                method,
                path,
                body=json.dumps(value) if value is not None else None,
                headers=headers or {},
            )
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()

    def create(self):
        status, body, _ = self.request(
            "POST",
            "/api/analysis/jobs",
            {"repository": "tiny-shop", "question": "overview"},
            self.headers,
        )
        self.assertEqual(status, 200)
        return json.loads(body)

    def test_ui_to_backend_report_source_links_export_and_readonly_history(self):
        status, html, headers = self.request("GET", "/analysis")
        self.assertEqual(status, 200)
        self.assertIn(b"No model calls", html)
        self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
        job = self.create()
        path = "/api/analysis/jobs/" + job["job_id"]
        self.assertEqual(self.request("POST", path + "/start", {}, self.headers)[0], 200)
        self.control.thread.join(5)
        status, body, _ = self.request("GET", path + "/report")
        self.assertEqual(status, 200)
        report = json.loads(body)
        self.assertEqual(len(report["report"]["claims"]), 3)
        self.assertEqual(report["model_requests"], 0)
        status, body, _ = self.request("GET", path + "/files/inventory.py")
        self.assertEqual(status, 200)
        self.assertIn(b'id="L5"', body)
        self.assertIn(b"return price * quantity", body)
        status, body, headers = self.request("GET", path + "/download")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        with zipfile.ZipFile(io.BytesIO(body)) as bundle:
            self.assertIn("files/inventory.py", bundle.namelist())
        self.assertEqual(self.request("POST", path + "/start", {}, self.headers)[0], 409)
        status, body, _ = self.request("GET", "/api/runs")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["total"], 1)
        self.assertEqual(self.request("POST", "/api/tasks", {}, self.headers)[0], 403)
        snapshot = self.control.directory / job["job_id"] / "files/README.md"
        snapshot.write_text("tampered")
        self.assertEqual(self.request("GET", path + "/download")[0], 409)

    def test_origin_csrf_body_and_unknown_file_scope_guards(self):
        value = {"repository": "tiny-shop", "question": "overview"}
        for changed in ({"Origin": "https://evil.test"}, {"X-CAS-CSRF": "wrong"}):
            headers = self.headers | changed
            self.assertEqual(self.request("POST", "/api/analysis/jobs", value, headers)[0], 403)
        self.assertEqual(
            self.request("GET", "/api/analysis", headers={"Host": "evil.test"})[0], 403
        )
        for wrong in (
            value | {"allow_live": True},
            value | {"repository": "../auth"},
            [],
            value | {"question": "send repository"},
        ):
            self.assertEqual(
                self.request("POST", "/api/analysis/jobs", wrong, self.headers)[0], 409
            )
        self.assertEqual(
            self.request(
                "POST", "/api/analysis/jobs", value, self.headers | {"Content-Length": "2048"}
            )[0],
            409,
        )
        self.assertEqual(self.control.list(), [])
        job = self.create()
        self.control.start(job["job_id"])
        self.control.thread.join(5)
        for name in (".env", "response.json", "..%2fsecret", "C:%5cauth"):
            self.assertNotEqual(
                self.request("GET", f"/api/analysis/jobs/{job['job_id']}/files/{name}")[0], 200
            )

    def test_default_console_does_not_enable_analysis(self):
        server = create_server(self.control.root, port=0)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            connection.request("GET", "/analysis")
            response = connection.getresponse()
            self.assertEqual(response.status, 404)
            response.read()
            connection.close()
        finally:
            server.shutdown()
            thread.join()
            server.server_close()
