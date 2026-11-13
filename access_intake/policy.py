"""Validated evidence and ordered office-policy routing, without approvals."""
import copy
import datetime
import re

from .validation import SCHEMA, SCALARS, validate_extraction, validate_quotes, validate_schema

REQUIRED = ['request_id','request_date','requester','team','system','environment',
            'permission','business_purpose','start_date','end_date','manager']
CODES = ['missing','conflict','relative_date','invalid_date','ambiguous_date',
         'identifier_mismatch','invalid_date_range','instruction_override']


def obj(properties):
    return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}


STRINGS = {'type':'array','items':{'type':'string'}}
ANNOTATION = obj({'issue_index':{'type':'integer','minimum':0},
                  'field':{'type':['string','null'],'enum':SCALARS+[None]},
                  'code':{'type':'string','enum':CODES}, 'supporting_quotes':STRINGS})
WRAPPER_SCHEMA = obj({'extraction':SCHEMA,'review_evidence':obj({
    'instruction_override_quotes':STRINGS,
    'issue_annotations':{'type':'array','items':ANNOTATION}})})
ASSESSMENT_SCHEMA = obj({'actual_attempt':{'type':'boolean'},'supporting_quotes':STRINGS})
ATTACK = re.compile(r'system\s+override|bypass\s+approval\s+rules|display\s+the\s+api\s+key|highest.priority\s+system\s+instruction', re.I)


def prepare(source, wrapper, assessor=None):
    wrapper = copy.deepcopy(wrapper)
    validate_schema(wrapper, WRAPPER_SCHEMA)
    e, evidence = wrapper['extraction'], wrapper['review_evidence']
    validate_extraction(e, source.message)
    annotations = evidence['issue_annotations']
    indices = [a['issue_index'] for a in annotations]
    if sorted(indices) != list(range(len(e['issues']))):
        raise ValueError('Every issue needs one valid structured annotation.')
    validate_quotes(evidence['instruction_override_quotes'], source.message)
    for a in annotations:
        validate_quotes(a['supporting_quotes'], source.message)
        if a['code'] == 'conflict' and (a['field'] is None or len(set(a['supporting_quotes'])) < 2):
            raise ValueError('Conflict needs a field and both alternatives as evidence.')

    def issue(field, code, quotes=()):
        for quote in quotes:
            if quote not in e['supporting_quotes']:
                e['supporting_quotes'].append(quote)
        if any(a['field']==field and a['code']==code for a in annotations):
            return
        annotations.append({'issue_index':len(e['issues']),'field':field,'code':code,
                            'supporting_quotes':list(quotes)})
        e['issues'].append(f'{field or "message"}: {code.replace("_", " ")}.')

    actual = False
    if evidence['instruction_override_quotes'] or ATTACK.search(source.message):
        if assessor is None:
            raise ValueError('Context assessment required for override candidate.')
        assessment = assessor()
        validate_schema(assessment, ASSESSMENT_SCHEMA)
        validate_quotes(assessment['supporting_quotes'],source.message)
        actual = assessment['actual_attempt']
        if actual and not any(q.strip() for q in assessment['supporting_quotes']):
            raise ValueError('An actual attempt needs exact source evidence.')
        evidence['override_assessment'] = assessment
    # Only the final context verdict can establish an override, never issue prose.
    keep = [a for a in annotations if a['code'] != 'instruction_override']
    old_issues = e['issues']
    e['issues'] = [old_issues[a['issue_index']] for a in keep]
    for index, a in enumerate(keep): a['issue_index'] = index
    annotations[:] = keep
    evidence['instruction_override_quotes'] = []
    if actual:
        evidence['instruction_override_quotes'] = assessment['supporting_quotes']
        issue(None,'instruction_override',assessment['supporting_quotes'])

    for a in list(annotations):
        if a['code']=='conflict': e[a['field']]=None
    for field in SCALARS:
        value=e[field]
        if isinstance(value,str) and not value.strip(): e[field]=None
        if field in ('request_date','start_date','end_date') and e[field] is not None:
            value=e[field]
            try:
                if not re.fullmatch(r'\d{4}-\d\d-\d\d',value): raise ValueError()
                datetime.date.fromisoformat(value)
            except ValueError:
                code='ambiguous_date' if re.search(r'\d/\d',value) else 'invalid_date'
                if re.search(r'next|tomorrow|today|monday|friday',value,re.I): code='relative_date'
                e[field]=None
                issue(field,code,[value] if value in source.message else [])
        if e[field] is None and not any(a['field']==field for a in annotations):
            issue(field,'missing')
    if e['request_id'] and source.document_id.removesuffix('.json') != e['request_id']:
        issue('request_id','identifier_mismatch')
    if e['start_date'] and e['end_date'] and e['start_date']>e['end_date']:
        issue('start_date','invalid_date_range')
    validate_extraction(e,source.message)
    if actual:
        route=('review','IT Service Desk','inspect-message')
    elif e['kind']=='withdrawal' and e['request_id'] and e['request_date']:
        route=('review','IT Service Desk','confirm-withdrawal')
    elif (e['kind'] not in ('new','change') or any(e[f] is None for f in REQUIRED)
          or any(a['code'] in ('conflict','identifier_mismatch','invalid_date_range') for a in annotations)):
        route=('needs-information','IT Service Desk','clarify')
    elif e['environment']=='production' or e['permission'] in ('write','admin'):
        route=('review','Security Review','review-risk-then-owner')
    else:
        route=('review','System Owner','review-request')
    return dict(wrapper,status=route[0],owner=route[1],next_action=route[2])
