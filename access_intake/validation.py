"""Structural validation, original-byte identity and exact source evidence."""
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator

RESOURCES = Path(__file__).parent / 'resources'
SCHEMA = json.loads((RESOURCES / 'snapshot.schema.json').read_text())
SCALARS = [k for k in SCHEMA['required'] if k not in ('supporting_quotes', 'issues')]


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON property.')
        result[key] = value
    return result


def strict_json(text):
    return json.loads(text, object_pairs_hook=_unique_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Non-JSON number.')))


@dataclass(frozen=True)
class Source:
    document_id: str
    raw: bytes
    message: str
    metadata: dict

    @property
    def source_sha256(self):
        return hashlib.sha256(self.raw).hexdigest()

    @property
    def context(self):
        return {'document_id': self.document_id, 'source_sha256': self.source_sha256}


def load_source(path, raw=None):
    path = Path(path)
    raw = path.read_bytes() if raw is None else raw
    try:
        data = strict_json(raw.decode('utf-8'))
        if not isinstance(data, dict) or not isinstance(data.get('message'), str):
            raise ValueError('Export must contain a message string.')
        metadata = {k: data.get(k) for k in ('export_version', 'exported_at', 'source_channel', 'subject')}
        return Source(path.name, raw, data['message'], metadata)
    except (UnicodeError, ValueError) as exc:
        raise ValueError('Input must be UTF-8 JSON with unique properties and a message string.') from exc


def validate_schema(value, schema):
    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda e: str(e.path))
    if errors:
        # Do not include model content or credentials from a library error message.
        raise ValueError('Schema validation failed at ' + '/'.join(map(str, errors[0].path)) + '.')


def validate_quotes(quotes, message):
    if any(q not in message for q in quotes):
        raise ValueError('Evidence is not an exact decoded-message substring.')


def validate_extraction(value, message):
    validate_schema(value, SCHEMA)
    validate_quotes(value['supporting_quotes'], message)
    return value
