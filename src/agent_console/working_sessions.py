"""Local-owner finite-session console bridge."""

import hmac
import json
import os
import secrets
import subprocess
import sys
import threading


class WorkingSessionBridge:
    def __init__(self, controller):
        self.controller = controller
        self.token = secrets.token_urlsafe(32)
        self._launch_lock = threading.Lock()
        self._launches = {}

    def _view(self, record):
        with self._launch_lock:
            process = self._launches.get(record['session_id'])
            if process is not None and record['status'] == 'PREPARED':
                code = process.poll()
                if code is not None and code != 0:
                    record['launch_error'] = 'Local task process could not start; inspect the session before trying again.'
            elif process is not None and process.poll() is not None:
                self._launches.pop(record['session_id'], None)
        return record

    def info(self):
        return {
            "enabled": True,
            "csrf": self.token,
            "sessions": [self._view(record) for record in self.controller.list()],
            "mode": "local-owner-console" if os.environ.get('CAS_LOCAL_OWNER_AUTH_FILE')
                    else "private-local-terminal-only",
            "max_tasks": 2,
            "context_isolation": "NOT_PROVED",
        }

    def get(self, path):
        try:
            return self._get(path)
        except (ValueError, TypeError, KeyError, RecursionError, OSError, RuntimeError):
            raise ValueError("WORKING_SESSION_STATE_UNAVAILABLE") from None

    def _get(self, path):
        if path == "/api/working-sessions":
            return self.info()
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[:2] == ["api", "working-sessions"]:
            return self._view(self.controller.get(parts[2]))
        if (
            len(parts) == 4
            and parts[:2] == ["api", "working-sessions"]
            and parts[3] == "scope"
        ):
            return self.controller.scope(parts[2])
        raise ValueError("WORKING_SESSION_ACTION_REJECTED")

    def post(self, handler):
        try:
            return self._post(handler)
        except (ValueError, TypeError, KeyError, RecursionError, OSError, RuntimeError):
            raise ValueError("WORKING_SESSION_ACTION_REJECTED") from None

    def _post(self, handler):
        host = handler.headers.get("Host", "")
        if (
            host
            not in {
                f"127.0.0.1:{handler.server.server_port}",
                f"localhost:{handler.server.server_port}",
            }
            or handler.headers.get("Origin") != "http://" + host
            or not hmac.compare_digest(
                handler.headers.get("X-CAS-CSRF", ""), self.token
            )
        ):
            raise ValueError("WORKING_SESSION_ACTION_REJECTED")
        if (
            handler.headers.get("Content-Type") != "application/json"
            or handler.headers.get("Transfer-Encoding") is not None
        ):
            raise ValueError("WORKING_SESSION_ACTION_REJECTED")
        length = int(handler.headers.get("Content-Length", "0"))
        if not 0 < length <= 8192:
            raise ValueError("WORKING_SESSION_ACTION_REJECTED")
        handler.connection.settimeout(5)
        raw = handler.rfile.read(length)
        if len(raw) != length:
            raise ValueError("WORKING_SESSION_ACTION_REJECTED")

        def unique(items):
            d = {}
            for k, v in items:
                if k in d:
                    raise ValueError("WORKING_SESSION_ACTION_REJECTED")
                d[k] = v
            return d

        try:
            value = json.loads(raw, object_pairs_hook=unique)
            if not isinstance(value, dict):
                raise ValueError("WORKING_SESSION_ACTION_REJECTED")  # noqa: TRY004 - closed HTTP error contract
            if handler.path == "/api/working-sessions" and set(value) == {"title"}:
                return self.controller.create(value["title"])
            parts = handler.path.strip("/").split("/")
            if len(parts) != 4 or parts[:2] != ["api", "working-sessions"]:
                raise ValueError("WORKING_SESSION_ACTION_REJECTED")
            sid, action = parts[2:]
            if action == "tasks" and set(value) == {"title", "prompt"}:
                return self.controller.add(sid, **value)
            if action == "prepare" and value == {}:
                return self.controller.prepare(sid)
            if action == 'run' and set(value) == {'plan_hash'}:
                with self._launch_lock:
                    previous = self._launches.get(sid)
                    record = self.controller.get(sid)
                    if (previous is not None and previous.poll() is None or
                        record['status'] != 'PREPARED' or
                        record['plan_hash'] != value['plan_hash'] or
                        not record.get('local_auth_mode')):
                        raise ValueError('WORKING_SESSION_ACTION_REJECTED')
                    if any(process.poll() is None for other, process in self._launches.items()
                           if other != sid):
                        return {'accepted': False, 'session_id': sid, 'reason': 'WORKING_SESSION_BUSY'}
                    if any(other['session_id'] != sid and other['status'] in
                           {'STARTING', 'LOGIN_REQUIRED', 'RUNNING', 'CANCEL_REQUESTED', 'ENDING'}
                           for other in self.controller.list()):
                        return {'accepted': False, 'session_id': sid, 'reason': 'WORKING_SESSION_BUSY'}
                    # Child repeats validation and consumes the one-shot claim.
                    self.controller.scope(sid)
                    try:
                        self.controller.validate_new_input(self.controller.load(sid))
                    except ValueError:
                        return {'accepted': False, 'session_id': sid, 'reason': 'WORKING_SESSION_INPUT_REQUIRES_NEW_TASK'}
                    self._launches[sid] = subprocess.Popen(
                        [sys.executable, '-B', '-m', 'agent_runtime',
                         '--root', str(self.controller.root), '--data-dir', str(self.controller.data_dir),
                         'working-session', 'run', sid, '--allow-live'],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        close_fds=True,
                        creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW)
                        if sys.platform == 'win32' else 0,
                    )
                return {'accepted': True, 'session_id': sid}
            if action in {"cancel", "end"} and set(value) == {"plan_hash"}:
                return self.controller.request(
                    sid, value["plan_hash"], end=action == "end"
                )
            raise ValueError("WORKING_SESSION_ACTION_REJECTED")
        except (ValueError, TypeError, KeyError, RecursionError, OSError, RuntimeError):
            raise ValueError("WORKING_SESSION_ACTION_REJECTED") from None
