"""Source-pinned exact comparison and separate, explicitly supplied human review."""
import json
from pathlib import Path
from .validation import SCALARS


def compare_records(expected,actual,reviews=None):
    reviews=reviews or {}
    report={'scalar_total':12*len(expected),'scalar_matches':0,'route_total':3*len(expected),'route_matches':0,
            'scalar_discrepancies':[],'route_discrepancies':[],'structural_errors':[],'quote_errors':[],
            'issue_errors':[],'factual_errors':[],'purpose_review':{'correct':0,'incorrect':0,'unassessed':0,'total':len(expected)},
            'response_sources':sorted({r.get('response_source','unknown') for r in actual if isinstance(r,dict)}),
            'interpretation':'Mock agreement validates pipeline/comparison behavior, not live model accuracy.'}
    indexed={}
    expected_ids={r['document_id'] for r in expected}
    if len(expected_ids)!=len(expected): raise ValueError('Expected facts contain duplicate document IDs.')
    for record in actual:
        if not isinstance(record,dict) or not isinstance(record.get('document_id'),str):
            report['structural_errors'].append('Actual record lacks document_id.')
            continue
        doc=record['document_id']
        if doc in indexed: report['structural_errors'].append('Duplicate current record: '+doc)
        else: indexed[doc]=record
        if doc not in expected_ids: report['structural_errors'].append('Unexpected document: '+doc)
    for oracle in expected:
        doc=oracle['document_id']
        record=indexed.get(doc,{})
        if not record: report['structural_errors'].append('Missing document: '+doc)
        if record and record.get('source_sha256')!=oracle.get('source_sha256'):
            report['structural_errors'].append('Source version differs from expected facts: '+doc)
        extraction=record.get('extraction')
        valid=isinstance(extraction,dict)
        for field in SCALARS:
            expected_value=oracle['extraction'][field]
            value=extraction.get(field) if valid else None
            if valid and field in extraction and value==expected_value:
                report['scalar_matches']+=1
            else:
                report['scalar_discrepancies'].append({'document_id':doc,'field':field,'expected':expected_value,
                    'actual':value,'source':oracle['source_evidence'],
                    'reason':'wording or fact mismatch; check source' if field=='business_purpose' and valid else 'missing or different fact'})
        for field in ('status','owner','next_action'):
            if record.get(field)==oracle[field]: report['route_matches']+=1
            else: report['route_discrepancies'].append({'document_id':doc,'field':field,'expected':oracle[field],
                                                       'actual':record.get(field),'source':oracle['source_evidence']})
        quotes=extraction.get('supporting_quotes',[]) if valid else []
        if not isinstance(quotes,list): quotes=[]
        for quote in quotes:
            if not isinstance(quote,str) or quote not in oracle['source_message']:
                report['quote_errors'].append({'document_id':doc,'quote':quote,'reason':'not an exact source substring'})
        for term in oracle.get('required_evidence_terms',[]):
            if not any(isinstance(q,str) and term in q for q in quotes):
                report['quote_errors'].append({'document_id':doc,'term':term,'reason':'required conflict/override evidence missing'})
        wanted={(a['field'],a['code']) for a in oracle.get('issue_categories',[])}
        evidence=record.get('review_evidence') or {}
        got={(a.get('field'),a.get('code')) for a in evidence.get('issue_annotations',[]) if isinstance(a,dict)}
        if wanted!=got:
            report['issue_errors'].append({'document_id':doc,'missing':sorted(wanted-got,key=str),
                                          'unsupported':sorted(got-wanted,key=str),'source':oracle['source_evidence']})
        review=reviews.get(doc)
        verdict=review.get('verdict','unassessed') if isinstance(review,dict) else 'unassessed'
        if verdict not in ('correct','incorrect','unassessed'): raise ValueError('Unsupported review verdict.')
        if verdict!='unassessed':
            if not valid or not review.get('source_quote') or review['source_quote'] not in oracle['source_message'] or not review.get('rationale'):
                raise ValueError('Reviewed verdicts need a valid extraction, exact source quotation and rationale.')
        report['purpose_review'][verdict]+=1
        if verdict=='incorrect': report['factual_errors'].append({'document_id':doc,'field':'business_purpose','review':review})
    report['factual_errors'].extend(report['quote_errors'])
    report['purpose_review']['reviewed']=report['purpose_review']['correct']+report['purpose_review']['incorrect']
    return report


def compare_files(expected_directory,actual_path):
    expected=[json.loads(p.read_text()) for p in sorted(Path(expected_directory).glob('*.json'))]
    if not expected: raise ValueError('No source-authored expected records found.')
    actual=[json.loads(line) for line in Path(actual_path).read_text().splitlines() if line.strip()]
    return compare_records(expected,actual)
