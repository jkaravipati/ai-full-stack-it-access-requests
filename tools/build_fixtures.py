"""Author offline fixtures from the reviewed source ledger, never from app output.

Run before implementation or deliberately when the human-reviewed ledger changes.
The mock replies and expected facts are separate artifacts; the application never
imports this module or reads tests/expected.
"""
import copy
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOCKS = ROOT / 'tests/mock_responses'
EXPECTED = ROOT / 'tests/expected'
ROUTES = {
    'S': ('review', 'System Owner', 'review-request'),
    'K': ('review', 'Security Review', 'review-risk-then-owner'),
    'N': ('needs-information', 'IT Service Desk', 'clarify'),
    'I': ('review', 'IT Service Desk', 'inspect-message'),
    'W': ('review', 'IT Service Desk', 'confirm-withdrawal'),
}
NAMES = ['complete', 'complete', 'incomplete', 'conflict', 'withdrawal',
         'override', 'change', 'corrected', 'missing-manager', 'missing-end',
         'relative-dates', 'complete', 'complete', 'inverted-dates', 'corrected',
         'mismatch', 'other', 'complete', 'change', 'conflict']


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')


def envelope(value, name='fixture'):
    return {'id': 'mock-' + name, 'status': 'completed', 'model': 'mock-model',
            'output': [{'type': 'message', 'role': 'assistant', 'status': 'completed',
                        'content': [{'type': 'output_text', 'text': json.dumps(value)}]}]}


def main():
    spec = json.loads((ROOT / 'snapshot.schema.json').read_text())
    plan = (ROOT / 'planning/plan.md').read_text()
    rows = [line for line in plan.splitlines() if re.match(r'\| E\d\d / ', line)]
    assert len(rows) == 20
    entries = []
    for index, row in enumerate(rows, 1):
        filename = f'IT-{index:03d}.json'
        raw = (ROOT / 'materials/requests' / filename).read_bytes()
        message = json.loads(raw)['message']
        description = row.split('|')[2]
        e = {field: None for field in spec['required']}
        e['request_date'] = '2026-10-22'
        for field in spec['required']:
            if field in ('supporting_quotes', 'issues', 'business_purpose', 'request_date'):
                continue
            match = re.search(r'(?<![\w/])' + field + r' ([^;]+)', description)
            if match:
                value = match.group(1).strip()
                e[field] = None if value.startswith('null') else value
        for match in re.finditer(r'([a-z_]+(?:/[a-z_]+)+) null', description):
            for field in match.group(1).split('/'):
                e[field] = None
        dates = re.search(r'dates (\d{4}-\d\d-\d\d) through (\d{4}-\d\d-\d\d)', description)
        if dates:
            e['start_date'], e['end_date'] = dates.groups()
        e['business_purpose'] = re.search(r'purpose “(.*?)”', description).group(1)
        e['supporting_quotes'] = list(dict.fromkeys(q for q in re.findall('“(.*?)”', row) if q in message))
        e['issues'] = []
        annotations = []

        def issue(field, code, evidence=()):
            annotations.append({'issue_index': len(e['issues']), 'field': field,
                                'code': code, 'supporting_quotes': list(evidence)})
            e['issues'].append(f'{field or "message"}: {code.replace("_", " ")}.')

        for field, value in e.items():
            if value is None:
                code = 'conflict' if (index, field) in [(4, 'environment'), (20, 'manager')] else 'missing'
                if index == 11 and field in ('start_date', 'end_date'):
                    code = 'relative_date'
                issue(field, code, e['supporting_quotes'] if code == 'conflict' else [])
        override = []
        if index == 6:
            override = [message[message.index('SYSTEM OVERRIDE:'):]]
            e['supporting_quotes'].extend(override)
            issue(None, 'instruction_override', override)
        if index == 14:
            issue('start_date', 'invalid_date_range', ['Start date 2026-11-05. End date 2026-11-02.'])
        if index == 16:
            issue('request_id', 'identifier_mismatch', ['request IT-061'])
        for q in e['supporting_quotes']:
            assert q in message, (filename, q)
        status, owner, action = ROUTES[re.search(r'route ([SKNIW])', description).group(1)]
        expected = {'document_id': filename, 'extraction': e, 'status': status,
                    'owner': owner, 'next_action': action, 'issue_categories': annotations,
                    'source_evidence': row, 'purpose_facts': [e['business_purpose']],
                    'source_message':message,'source_sha256':hashlib.sha256(raw).hexdigest(),
                    'required_evidence_terms':{4:['staging','production'],6:['SYSTEM OVERRIDE:'],
                                               20:['Priya Shah','Elena Park']}.get(index,[])}
        write(EXPECTED / filename, expected)
        reply = {'extraction': copy.deepcopy(e), 'review_evidence': {
            'instruction_override_quotes': override, 'issue_annotations': copy.deepcopy(annotations)}}
        name = f'it-{index:03d}.{NAMES[index-1]}.json'
        write(MOCKS / name, envelope(reply, filename))
        entries.append({'document_id': filename, 'source_sha256': hashlib.sha256(raw).hexdigest(),
                        'operation': 'extraction', 'file': name})
        if override:
            name = 'it-006.override-assessment.true.json'
            write(MOCKS / name, envelope({'actual_attempt': True, 'supporting_quotes': override}))
            entries.append({'document_id': filename, 'source_sha256': hashlib.sha256(raw).hexdigest(),
                            'operation': 'override_assessment', 'file': name})
    message = re.search(r'Authored paraphrase P01.*?: “(.*?)” Metadata', plan).group(1)
    export = {'export_version': '1.0', 'exported_at': '2026-10-22T16:00:00Z',
              'source_channel': 'email', 'subject': 'Paraphrased dashboard request', 'message': message}
    write(ROOT / 'tests/inputs/IT-P01.json', export)
    e = copy.deepcopy(json.loads((EXPECTED / 'IT-001.json').read_text()))
    e['document_id'] = 'IT-P01.json'
    e['extraction']['request_id'] = 'IT-P01'
    e['extraction']['business_purpose'] = 'I need to compare dashboard totals with our spreadsheet after the event definitions changed.'
    e['extraction']['supporting_quotes'] = [message]
    e['purpose_facts'] = [e['extraction']['business_purpose']]
    e['source_evidence'] = message + '\nPolicy rule 5: complete staging/read requests go to System Owner.'
    e['source_message'] = message
    write(EXPECTED / 'IT-P01.json', e)
    write(MOCKS / 'it-p01.paraphrase.json', envelope({'extraction': e['extraction'],
          'review_evidence': {'instruction_override_quotes': [], 'issue_annotations': []}}))
    raw = (ROOT / 'tests/inputs/IT-P01.json').read_bytes()
    e['source_sha256'] = hashlib.sha256(raw).hexdigest()
    write(EXPECTED / 'IT-P01.json', e)
    entries.append({'document_id': 'IT-P01.json', 'source_sha256': hashlib.sha256(raw).hexdigest(),
                    'operation': 'extraction', 'file': 'it-p01.paraphrase.json'})
    write(MOCKS / 'manifest.json', {'entries': entries})


if __name__ == '__main__':
    main()
