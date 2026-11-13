"""Provider boundary; the mock reads saved replies, never expected fixtures."""
import hashlib
import json
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class ProviderError(Exception):
    def __init__(self, code, message, stage='extraction'):
        super().__init__(message)
        self.code, self.stage = code, stage


class MockProvider:
    response_source = 'mock'
    origin = 'mock'

    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.entries = json.loads((self.directory / 'manifest.json').read_text())['entries']
        self.calls = []
        self._lock = threading.Lock()
        digest = hashlib.sha256()
        for path in sorted(self.directory.glob('*')):
            if path.is_file():
                digest.update(path.name.encode())
                digest.update(path.read_bytes())
        self.config = {'provider': 'mock', 'mock_responses': str(self.directory),
                       'fixtures_sha256': digest.hexdigest(), 'model': 'mock-model'}

    def call(self, operation, message, context):
        with self._lock:
            self.calls.append(operation)
        entry = next((e for e in self.entries if e['document_id'] == context['document_id']
                      and e['source_sha256'] == context['source_sha256']
                      and e['operation'] == operation), None)
        if not entry:
            raise ProviderError('missing_fixture', 'No mock fixture for this source hash and operation.', operation)
        path = (self.directory / entry['file']).resolve()
        if not path.is_relative_to(self.directory):
            raise ProviderError('invalid_fixture', 'Mock fixture path escapes its directory.', operation)
        response = json.loads(path.read_text())
        if 'mock_error' in response:
            raise ProviderError(response['mock_error'], 'Scripted mock provider failure.', operation)
        return response


DEFAULT_CONFIG = {'provider': 'openai', 'endpoint': 'https://api.openai.com/v1/responses',
                  'model': 'gpt-5.6-terra', 'max_output_tokens': 4096,
                  'reasoning_effort': 'none', 'timeout': 60}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_transport(url, headers, request, timeout):
    request = urllib.request.Request(url, data=json.dumps(request).encode(), headers=headers, method='POST')
    opener = urllib.request.build_opener(NoRedirect)
    with opener.open(request, timeout=timeout) as response:
        data = response.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024:
            raise ProviderError('response_too_large', 'Provider response exceeds the supported size.')
        return data


class OpenAIProvider:
    """Live transport is optional and replaced in every automated provider test."""
    def __init__(self, config=None, transport=None, credential_getter=None, origin='provider'):
        config = config or {}
        if set(config) - set(DEFAULT_CONFIG):
            raise ValueError('Unsupported provider configuration key; credentials belong in the environment.')
        self.config = dict(DEFAULT_CONFIG, **config)
        if self.config['provider'] != 'openai':
            raise ValueError('The live adapter supports provider openai only.')
        parsed = urllib.parse.urlsplit(self.config['endpoint'])
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Provider endpoint must be HTTPS without credentials, query or fragment.')
        if not isinstance(self.config['model'], str) or not self.config['model']:
            raise ValueError('A model ID is required.')
        if type(self.config['max_output_tokens']) is not int or self.config['max_output_tokens'] < 1:
            raise ValueError('max_output_tokens must be positive.')
        if not isinstance(self.config['timeout'], (int, float)) or self.config['timeout'] <= 0:
            raise ValueError('timeout must be positive.')
        self.transport = transport or http_transport
        self.credential_getter = credential_getter or (lambda: os.environ.get('API_KEY'))
        self.origin = origin
        self.response_source = 'mock' if origin == 'mock' else 'openai:' + self.config['model']
        self._secrets = []

    def build_request(self, operation, message, context):
        from .policy import WRAPPER_SCHEMA, ASSESSMENT_SCHEMA
        from .validation import RESOURCES
        if operation not in ('extraction', 'override_assessment'):
            raise ValueError('Unsupported provider operation.')
        schema = WRAPPER_SCHEMA if operation == 'extraction' else ASSESSMENT_SCHEMA
        return {'model': self.config['model'], 'reasoning': {'effort': self.config['reasoning_effort']},
                'max_output_tokens': self.config['max_output_tokens'], 'stream': False, 'store': False, 'tools': [],
                'instructions': (RESOURCES / (operation + '.txt')).read_text(),
                'input': [{'role': 'user', 'content': json.dumps({'document_id': context['document_id'], 'message': message})}],
                'text': {'format': {'type': 'json_schema', 'name': 'access_' + operation,
                                    'strict': True, 'schema': schema}}}

    def redact(self, value):
        if isinstance(value, dict):
            return {k: '[REDACTED]' if k.lower() in ('authorization', 'api_key') else self.redact(v) for k, v in value.items()}
        if isinstance(value, list): return [self.redact(v) for v in value]
        if isinstance(value, str):
            for secret in self._secrets:
                value = value.replace(secret, '[REDACTED]')
            return re.sub(r'(?i)Bearer\s+[^\s,;]+', 'Bearer [REDACTED]', value)
        return value

    def request_evidence(self, source):
        return {'origin': 'mock-transport example; no live observation', 'configuration': self.config,
                'requests': [{'operation': op, 'url': self.config['endpoint'],
                              'headers': {'Authorization': '[REDACTED]', 'Content-Type': 'application/json'},
                              'body': self.build_request(op, source.message, source.context)}
                             for op in ('extraction', 'override_assessment')]}

    def call(self, operation, message, context):
        key = self.credential_getter()
        if not key:
            raise ProviderError('missing_api_key', 'Set API_KEY for live provider mode; mocks need no key.', operation)
        self._secrets.append(key)
        try:
            return self.transport(self.config['endpoint'],
                                  {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
                                  self.build_request(operation, message, context), self.config['timeout'])
        except urllib.error.HTTPError as exc:
            raise ProviderError('http_' + str(exc.code), 'Provider HTTP failure; inspect configuration/service and retry.', operation) from None
        except (TimeoutError,):
            raise ProviderError('timeout', 'Provider call timed out; retry this document.', operation) from None
        except (urllib.error.URLError, OSError):
            raise ProviderError('connection_error', 'Provider connection failed; check service access and retry.', operation) from None
