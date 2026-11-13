"""One independent intake attempt, with explicit response and failure handling."""
import json
import shlex
from .policy import prepare
from .providers import ProviderError
from .validation import strict_json


def response_payload(response):
    if isinstance(response, bytes):
        response = strict_json(response.decode('utf-8'))
    if not isinstance(response, dict): raise ValueError('Invalid response envelope.')
    if response.get('error') is not None:
        raise ProviderError('provider_error', 'Provider reported an error; inspect service/configuration and retry.')
    if response.get('status') != 'completed':
        raise ProviderError('incomplete_response', 'Provider did not complete the response.')
    if not isinstance(response.get('model'),str) or not response['model'].strip():
        raise ValueError('Completed response must identify its producing model.')
    texts = []
    output = response.get('output')
    if not isinstance(output, list): raise ValueError('Missing response output.')
    for item in output:
        if not isinstance(item, dict): raise ValueError('Invalid output item.')
        if item.get('type') == 'reasoning': continue
        if item.get('type') != 'message' or item.get('role') != 'assistant' or item.get('status') != 'completed':
            raise ValueError('Unexpected or interrupted response item.')
        if not isinstance(item.get('content'), list): raise ValueError('Invalid content.')
        for block in item['content']:
            if not isinstance(block, dict): raise ValueError('Invalid content block.')
            if block.get('type') == 'refusal':
                raise ProviderError('refusal', 'Provider refused this request; inspect source and configuration before retry.')
            if block.get('type') != 'output_text' or not isinstance(block.get('text'), str):
                raise ValueError('Unexpected content block.')
            texts.append(block['text'])
    if len(texts) != 1: raise ValueError('Expected exactly one JSON output.')
    return strict_json(texts[0]), response


def process_message(source, provider):
    calls = []
    stage = 'extraction'
    base = dict(source.context, error=None, provider_calls=calls, response_source=provider.response_source,
                requested_model=provider.config.get('model'), returned_model=None,
                response_received=False, source_basis='attempted')

    def call(operation):
        nonlocal stage
        stage = operation
        trace = {'operation': operation, 'requested_model': provider.config.get('model'),
                 'returned_model': None, 'response_received': False, 'completion_status': None,
                 'origin': getattr(provider, 'origin', 'mock')}
        calls.append(trace)
        raw = provider.call(operation, source.message, source.context)
        if isinstance(raw, bytes): raw = strict_json(raw.decode('utf-8'))
        if isinstance(raw, dict):
            trace.update(response_received=True, returned_model=raw.get('model'), completion_status=raw.get('status'))
            base['response_received'] = True
            if operation == 'extraction':
                base['returned_model'] = raw.get('model')
                if raw.get('model'):
                    base['source_basis'] = 'received'
                    if getattr(provider, 'origin', 'mock') != 'mock':
                        base['response_source'] = 'openai:' + raw['model']
        payload, _ = response_payload(raw)
        return payload

    try:
        extraction = call('extraction')
        result = prepare(source, extraction, assessor=lambda: call('override_assessment'))
        base.update(result)
    except (ValueError, UnicodeError, TypeError, KeyError, ProviderError, TimeoutError) as exc:
        code = getattr(exc, 'code', 'timeout' if isinstance(exc, TimeoutError) else 'invalid_response')
        message = str(exc) if isinstance(exc, ProviderError) else 'Invalid or interrupted provider response; inspect evidence and retry.'
        base.update(extraction=None, review_evidence=None, status='error', owner='IT Service Desk', next_action='retry-extraction',
                    error={'stage': stage, 'code': code, 'message': message,
                           'retry_command': shlex.join(['python3','-m','access_intake','retry',source.document_id])})
    return provider.redact(base) if hasattr(provider, 'redact') else base
