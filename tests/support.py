import copy
from contextlib import ExitStack
import hashlib
import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def expected(number=1):
    name = f'IT-{number:03d}.json' if isinstance(number, int) else number
    return json.loads((ROOT / 'tests/expected' / name).read_text())


def source(number=1):
    from access_intake.validation import load_source
    path = ROOT / 'materials/requests' / f'IT-{number:03d}.json'
    return load_source(path)


def reply(number=1):
    from access_intake.providers import MockProvider
    s = source(number)
    return MockProvider(ROOT / 'tests/mock_responses').call('extraction', s.message, s.context)


def body(number=1):
    return json.loads(reply(number)['output'][0]['content'][0]['text'])


def envelope(value):
    return {'id': 'mock-script', 'status': 'completed', 'model': 'mock-model',
            'output': [{'type': 'message', 'role': 'assistant', 'status': 'completed',
                        'content': [{'type': 'output_text', 'text': json.dumps(value)}]}]}


class ScriptedProvider:
    origin = 'mock'
    response_source = 'mock'
    config = {'provider': 'mock', 'model': 'mock-model', 'script': 'test'}

    def __init__(self, *responses, hook=None):
        self.responses = list(responses)
        self.calls = []
        self.hook = hook

    def call(self, operation, message, context):
        self.calls.append(operation)
        if self.hook:
            return self.hook(operation, message, context)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return copy.deepcopy(response)


class OfflineTest(unittest.TestCase):
    def setUp(self):
        self.guards = ExitStack()
        self.addCleanup(self.guards.close)

        def forbid_network(*args, **kwargs):
            raise AssertionError('Tests must use saved mock responses; networking is forbidden.')

        # Preserve the socket class so importing ssl/HTTP modules remains valid,
        # while connection, DNS and datagram attempts fail before any network I/O.
        for target, attribute in [(socket, 'create_connection'), (socket, 'getaddrinfo'),
                                  (socket.socket, 'connect'), (socket.socket, 'connect_ex'),
                                  (socket.socket, 'sendto')]:
            self.guards.enter_context(patch.object(target, attribute, forbid_network))

        original_getitem = type(os.environ).__getitem__

        def forbid_key_read(environment, key):
            if key in ('API_KEY', b'API_KEY'):
                raise AssertionError('Tests must inject credentials, never read API_KEY.')
            return original_getitem(environment, key)

        # Mapping.get(), os.getenv() and environb also pass through __getitem__.
        self.guards.enter_context(patch.object(type(os.environ), '__getitem__', forbid_key_read))
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def variant(self, message, name='IT-001.json'):
        from access_intake.validation import load_source
        path = self.dir / name
        path.write_text(json.dumps({'message': message, 'subject': 'test', 'export_version': '1.0',
                                    'exported_at': '2099-01-01T00:00:00Z', 'source_channel': 'email'}))
        return load_source(path)
