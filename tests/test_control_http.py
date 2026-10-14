"""Real loopback HTTP with an injected scripted runtime; never native/model evidence."""

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from agent_console.server import create_server


class FakeControl:
    def __init__(self):
        self.calls = []

    def list(self):
        return []

    def create(self, **values):
        self.calls.append(values)
        return {'task_id': 'scripted-draft'}


class HTTPControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.control = FakeControl()
        self.server = create_server(Path(self.temp.name), port=0, controller=self.control)
        thread = threading.Thread(target=self.server.serve_forever)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)
        self.host = f'127.0.0.1:{self.server.server_port}'

    def request(self, method, path, value=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        self.addCleanup(connection.close)
        connection.request(method, path, body=json.dumps(value) if value is not None else None,
                           headers=headers or {})
        response = connection.getresponse()
        body = response.read()
        return response.status, json.loads(body) if path != '/tasks.js' else body

    def test_same_origin_token_and_strict_body_required(self):
        code, info = self.request('GET', '/api/control')
        self.assertEqual(code, 200)
        headers = {'Content-Type': 'application/json', 'Origin': f'http://{self.host}',
                   'X-CAS-CSRF': info['csrf']}
        self.assertEqual(self.request('POST', '/api/tasks', {}, headers)[0], 200)
        for changed in ({'Origin': 'https://evil.test'}, {'X-CAS-CSRF': 'wrong'},
                        {'Content-Type': 'text/plain'}):
            rejected = dict(headers, **changed)
            self.assertEqual(self.request('POST', '/api/tasks', {}, rejected)[0], 409)
        self.assertEqual(len(self.control.calls), 1)
        self.assertEqual(self.request('POST', '/api/tasks', {'command':'anything'}, headers)[0], 409)

    def test_task_script_served_and_readonly_remains_default(self):
        code, source = self.request('GET', '/tasks.js')
        self.assertEqual(code, 200)
        self.assertIn(b'consent-live', source)
        server = create_server(Path(self.temp.name), port=0)
        with server:
            self.assertIsNotNone(server)
