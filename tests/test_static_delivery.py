"""Read the actual checkout assets through real GET dispatch; no server/socket."""

import re
import types
import unittest
from unittest.mock import patch

from agent_console import server


class StaticDeliveryTests(unittest.TestCase):
    def test_every_script_referenced_by_root_is_delivered_by_real_handler(self):
        scripts = re.findall(
            r'<script\s+src="([^"]+)"', server.asset_bytes("index.html").decode()
        )
        self.assertIn("/working-sessions.js", scripts)
        for path in scripts:
            outputs = []
            handler = types.SimpleNamespace(
                headers={"Host": "127.0.0.1:8765"},
                server=types.SimpleNamespace(server_port=8765),
                path=path,
                respond=lambda body, media_type, status=200: outputs.append(
                    (status, media_type, body)
                ),
                json=lambda body, status=200: outputs.append((status, "error", body)),
            )
            server.Handler.do_GET(handler)
            self.assertEqual(len(outputs), 1)
            self.assertEqual(outputs[0][0], 200, path)
            self.assertEqual(outputs[0][1], "text/javascript; charset=utf-8")
            self.assertEqual(outputs[0][2], server.asset_bytes(path[1:]))

    def test_unknown_and_sensitive_asset_names_remain_rejected(self):
        for name in [
            "../owner-approval.json",
            "owner-approval.json",
            "policy.json",
            "missing.js",
        ]:
            with self.assertRaises(server.DataError) as error:
                server.asset_bytes(name)
            self.assertEqual(error.exception.status, 404)


if __name__ == "__main__":
    with (
        patch("socket.socket", side_effect=AssertionError("NO_SOCKET")),
        patch("subprocess.Popen", side_effect=AssertionError("NO_PROCESS")),
    ):
        unittest.main()
