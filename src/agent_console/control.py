"""Optional runtime bridge. Read-only console installations need no runtime dependency."""

import hmac
import json
import secrets


class ControlBridge:
    def __init__(self, controller):
        self.controller = controller
        self.token = secrets.token_urlsafe(32)

    def info(self):
        return {'enabled': True, 'csrf': self.token, 'tasks': self.controller.list(),
                'execution_mode': 'scripted-test-only' if getattr(self.controller, 'adapter_factory', None) else 'native',
                'profile': 'coding-fixture-v1', 'model': 'claude-haiku-5-5',
                'limits': {'max_turns': 6, 'max_budget_usd': '0.10', 'timeout_seconds': 60},
                'context_isolation': 'unverified'}

    def post(self, handler):
        host = handler.headers.get('Host', '')
        if (host not in {f'127.0.0.1:{handler.server.server_port}',
                         f'localhost:{handler.server.server_port}'}
                or handler.headers.get('Origin') != f'http://{host}'
                or not hmac.compare_digest(handler.headers.get('X-CAS-CSRF', ''), self.token)):
            raise ValueError('Same-origin control token is required')
        if (handler.headers.get('Content-Type') != 'application/json'
                or handler.headers.get('Transfer-Encoding') is not None):
            raise ValueError('Expected bounded JSON request')
        length = int(handler.headers.get('Content-Length', '0'))
        if not 0 < length <= 4096:
            raise ValueError('Control request exceeds limit')
        handler.connection.settimeout(5)
        value = json.loads(handler.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError('Expected control object')  # noqa: TRY004 - closed HTTP error contract
        if handler.path == '/api/tasks':
            if set(value) - {'resumes_run_id'}:
                raise ValueError('Unknown task fields')
            return self.controller.create(**value)
        parts = handler.path.strip('/').split('/')
        if len(parts) != 4 or parts[:2] != ['api', 'tasks']:
            raise ValueError('Unknown task endpoint')
        if parts[3] == 'start' and set(value) == {'allow_live', 'allow_existing_login'}:
            return self.controller.start(parts[2], **value)
        if parts[3] == 'stop' and value == {}:
            return self.controller.stop(parts[2])
        raise ValueError('Invalid task operation')
