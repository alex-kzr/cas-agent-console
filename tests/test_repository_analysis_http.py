"""Actual loopback HTTP, source validation and export; no native/provider adapter."""

import http.client
import io
import json
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

from agent_runtime.tasks.repository_analysis import AnalysisControl

from agent_console.repository_analysis import create_analysis_server
from agent_console.server import create_server


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

    def test_sdk_preview_closed_start_and_explicit_snapshot_boundary(self):
        status, body, _ = self.request(
            "POST",
            "/api/analysis/jobs",
            {
                "repository": "tiny-shop",
                "question": "overview",
                "mode": "sdk",
                "files": ["README.md"],
            },
            self.headers,
        )
        self.assertEqual(status, 200)
        job = json.loads(body)
        path = "/api/analysis/jobs/" + job["job_id"]
        status, body, _ = self.request("GET", path + "/preview")
        self.assertEqual(status, 200)
        preview = json.loads(body)
        self.assertFalse(preview["live_enabled"])
        self.assertEqual([s["path"] for s in preview["payload"]["snapshots"]], ["README.md"])
        consent = {
            "allow_live": True,
            "allow_existing_login": True,
            "snapshot_sha256": preview["snapshot_sha256"],
        }
        self.assertEqual(self.request("POST", path + "/start", consent, self.headers)[0], 403)
        self.assertFalse((self.control.root / "runs").exists())
        self.assertEqual(self.request("GET", path + "/files/inventory.py")[0], 409)
        self.assertEqual(self.control.load(job["job_id"])["status"], "DRAFT")
        for names in ([], ["../README.md"], ["README.md", "README.md"]):
            self.assertEqual(
                self.request(
                    "POST",
                    "/api/analysis/jobs",
                    {
                        "repository": "tiny-shop",
                        "question": "overview",
                        "mode": "sdk",
                        "files": names,
                    },
                    self.headers,
                )[0],
                409,
            )

    def serve(self, control):
        server = create_analysis_server(control, 0)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        return server

    def test_vs_scope_is_metadata_only_and_staging_stays_closed_over_http(self):
        from unittest.mock import patch

        from agent_runtime.tasks import vs_review_profile as vs

        boom = AssertionError("a closed gate must not read or stage any VS source")
        with (
            patch.object(vs, "read_manifest_files", side_effect=boom),
            patch.object(vs, "stage", side_effect=boom),
        ):
            status, body, _ = self.request("GET", "/api/analysis")
            self.assertEqual(status, 200)
            scope = json.loads(body)["vs_scope"]
            self.assertEqual(scope["mode"], "sdk-vs-api-review")
            self.assertEqual(scope["repository"], "vacancy-search-frontend")
            self.assertEqual(scope["files"], ["src/api.ts", "src/api.test.ts"])
            self.assertEqual(
                [(m["path"], m["bytes"]) for m in scope["manifest"]],
                [("src/api.ts", 3550), ("src/api.test.ts", 6932)],
            )
            self.assertEqual(scope["source_staging"], "closed")
            self.assertFalse(scope["live_enabled"])
            self.assertEqual(scope["scope_sha256"], vs.canonical().fingerprint)
            self.assertNotIn("content", json.dumps(scope))
            fixed = {
                "repository": scope["repository"],
                "question": scope["question"],
                "mode": scope["mode"],
                "files": scope["files"],
            }
            status, body, _ = self.request("POST", "/api/analysis/jobs", fixed, self.headers)
            self.assertEqual(status, 409)
            self.assertIn("staging is closed", json.loads(body)["error"])
            # No override field of any kind reaches the controller.
            for extra in ({"test_only": True}, {"contents": {}}, {"root": "C:\\other"}):
                status, _, _ = self.request(
                    "POST", "/api/analysis/jobs", fixed | extra, self.headers
                )
                self.assertEqual(status, 409)
        self.assertEqual(self.control.list(), [])
        self.assertFalse(any(p.is_dir() for p in self.control.directory.iterdir()))

    def test_vs_test_only_snapshot_preview_nested_file_route_and_closed_start(self):
        from agent_runtime.tasks import vs_review_profile as vs

        api, spec = vs.NAMES
        profile = vs.canonical().test_variant(
            {api: "export const fixture = 1;\r\nexport const other = 2;\n", spec: "// unrelated\n"}
        )
        control = AnalysisControl(Path(self.temp.name) / "vs-data", vs_profile=profile)
        self.addCleanup(control.close)
        job = control.create(vs.REPOSITORY, "review", list(vs.NAMES), vs.SCOPE_MODE)
        server = self.serve(control)
        self.server, original = server, self.server
        try:
            path = "/api/analysis/jobs/" + job["job_id"]
            status, body, _ = self.request("GET", path + "/preview")
            self.assertEqual(status, 200)
            preview = json.loads(body)
            self.assertFalse(preview["live_enabled"])
            self.assertEqual([s["path"] for s in preview["payload"]["snapshots"]], [api, spec])
            self.assertEqual([s["path"] for s in preview["scope"]["sources"]], [api, spec])
            self.assertEqual(preview["scope_sha256"], profile.fingerprint)
            status, body, _ = self.request("GET", path + "/files/src/api.ts")
            self.assertEqual(status, 200)
            self.assertIn(b"fixture", body)
            status, body, _ = self.request("GET", path + "/files/src%2Fapi.test.ts")
            self.assertEqual(status, 200)
            for name in ("src/other.ts", "api.ts", "src/", "../src/api.ts"):
                self.assertEqual(self.request("GET", path + "/files/" + name)[0], 409, name)
            consent = {
                "allow_live": True,
                "allow_existing_login": True,
                "snapshot_sha256": preview["snapshot_sha256"],
                "scope_sha256": preview["scope_sha256"],
            }
            headers = {**self.headers, "Origin": "http://" + f"127.0.0.1:{server.server_port}"}
            status, body, _ = self.request("GET", "/api/analysis")
            headers["X-CAS-CSRF"] = json.loads(body)["csrf"]
            self.assertEqual(self.request("POST", path + "/start", consent, headers)[0], 403)
            self.assertFalse((control.root / "runs").exists())
            self.assertEqual(control.load(job["job_id"])["status"], "DRAFT")
        finally:
            self.server = original

    def test_mean_scope_creation_preview_and_closed_gate_over_http(self):
        status, body, _ = self.request("GET", "/api/analysis")
        advertised = json.loads(body)["review_scope"]
        self.assertEqual(advertised["files"], ["mean.py"])
        self.assertFalse(advertised["live_enabled"])
        scoped = {
            "repository": advertised["repository"],
            "question": advertised["question"],
            "mode": advertised["mode"],
            "files": advertised["files"],
        }
        for wrong in (
            scoped | {"files": ["mean.py", "mean.py"]},
            scoped | {"files": ["README.md"]},
            scoped | {"question": "overview"},
        ):
            self.assertEqual(
                self.request("POST", "/api/analysis/jobs", wrong, self.headers)[0], 409
            )
        self.assertEqual(self.control.list(), [])
        status, body, _ = self.request("POST", "/api/analysis/jobs", scoped, self.headers)
        self.assertEqual(status, 200)
        job = json.loads(body)
        path = "/api/analysis/jobs/" + job["job_id"]
        status, body, _ = self.request("GET", path + "/preview")
        self.assertEqual(status, 200)
        preview = json.loads(body)
        self.assertEqual(preview["scope_sha256"], advertised["scope_sha256"])
        self.assertTrue(preview["scope_current"])
        self.assertFalse(preview["live_enabled"])
        self.assertEqual([s["path"] for s in preview["payload"]["snapshots"]], ["mean.py"])
        self.assertEqual(preview["scope"]["source"]["path"], "mean.py")
        self.assertEqual(preview["scope"]["tools"], [])
        self.assertEqual(preview["scope"]["bounds"]["logical_queries"], 1)
        self.assertEqual(preview["tools"], [])
        consent = {
            "allow_live": True,
            "allow_existing_login": True,
            "snapshot_sha256": preview["snapshot_sha256"],
            "scope_sha256": preview["scope_sha256"],
        }
        # The closed scope gate refuses even exact fresh consent; a changed scope is refused too.
        for sent in (
            consent,
            consent | {"scope_sha256": "0" * 64},
            consent | {"allow_live": False},
        ):
            self.assertEqual(self.request("POST", path + "/start", sent, self.headers)[0], 403)
        self.assertFalse((self.control.root / "runs").exists())
        self.assertEqual(self.control.load(job["job_id"])["status"], "DRAFT")

    def test_review_question_selects_versioned_findings_and_needs_sdk_mode(self):
        status, body, _ = self.request("GET", "/api/analysis")
        self.assertIn("review", json.loads(body)["questions"])
        offline = {"repository": "tiny-shop", "question": "review"}
        self.assertEqual(self.request("POST", "/api/analysis/jobs", offline, self.headers)[0], 409)
        self.assertEqual(
            self.request(
                "POST",
                "/api/analysis/jobs",
                offline | {"mode": "offline", "files": ["README.md"]},
                self.headers,
            )[0],
            409,
        )
        self.assertEqual(self.control.list(), [])
        status, body, _ = self.request(
            "POST",
            "/api/analysis/jobs",
            offline | {"mode": "sdk", "files": ["inventory.py"]},
            self.headers,
        )
        self.assertEqual(status, 200)
        job = json.loads(body)
        status, body, _ = self.request("GET", f"/api/analysis/jobs/{job['job_id']}/preview")
        self.assertEqual(status, 200)
        preview = json.loads(body)
        self.assertEqual(preview["payload"]["schema_version"], 2)
        self.assertFalse(preview["live_enabled"])
        # A v1 question keeps the historical payload version.
        overview = self.control.create("tiny-shop", "overview", ["README.md"], "sdk")
        status, body, _ = self.request("GET", f"/api/analysis/jobs/{overview['job_id']}/preview")
        self.assertEqual(json.loads(body)["payload"]["schema_version"], 1)
        # No completed review exists, so no report is invented.
        self.assertEqual(self.request("GET", f"/api/analysis/jobs/{job['job_id']}/report")[0], 409)

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
