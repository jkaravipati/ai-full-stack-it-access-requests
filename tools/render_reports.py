"""Render auditable evidence from independent oracles and saved observed runs.

Never writes expected facts or mock replies. Run after the documented mock intake,
export, accuracy command and full test suite; rerun after final test-run capture.
"""
import json
import re
from pathlib import Path

from access_intake.providers import OpenAIProvider
from access_intake.validation import load_source

ROOT=Path(__file__).resolve().parents[1]


def main():
    deliverables=ROOT/'deliverables'
    deliverables.mkdir(exist_ok=True)
    report=json.loads((ROOT/'planning/accuracy-run.json').read_text())
    expectations=[json.loads(p.read_text()) for p in sorted((ROOT/'tests/expected').glob('*.json'))]
    request=OpenAIProvider().request_evidence(load_source(ROOT/'materials/requests/IT-006.json'))
    request['response_handling']={
        'implementation':['access_intake/providers.py','access_intake/pipeline.py','access_intake/policy.py'],
        'completed':'Validate envelope completion/items, strict JSON, wrapper/extraction schema, quotes and annotations before routing.',
        'refusal':'Explicit error route, null extraction, preserved operation and actionable retry command.',
        'incomplete':'Incomplete status or cut-off JSON produces error; partial facts never enter the queue.',
        'provider_errors':'HTTP, connection and timeout errors are explicit; credential-bearing original error text is not persisted.',
        'override_assessment':'A candidate triggers one separate context check; a failed/refused/incomplete check fails intake, never becomes false.',
        'tests':'tests/test_04_provider.py T17-T21, using saved responses and injected transport only.'}
    request['documentation']=[
        'https://developers.openai.com/api/docs/models/gpt-5.6-terra',
        'https://developers.openai.com/api/docs/guides/structured-outputs',
        'https://developers.openai.com/api/reference/resources/responses/methods/create']
    (deliverables/'request-evidence.json').write_text(json.dumps(request,indent=2)+'\n')
    accuracy=['# Accuracy: source-derived expectations and mock observations','',
        'The 20 supplied messages and the authored P01 paraphrase have independently specified expected facts in `tests/expected/` and the reviewed ledger in `planning/plan.md`. No expected value was copied from application output. Each oracle pins the original-byte source hash, original message, field values, quotes, issues and route.','',
        '## Procedure and denominators','',
        'Run `.venv/bin/python -m access_intake accuracy --expected tests/expected --actual deliverables/extractions.jsonl`. Compare all 12 scalar properties exactly: 21 × 12 = 252 comparisons. Null matches null; no case/whitespace normalization occurs. Missing/failed extraction counts as 12 mismatches, including expected-null fields. Duplicate/unexpected/missing documents and source-version changes are structural findings.','',
        'Score status/owner/next_action independently: 21 × 3 = 63 comparisons. Compare quote substrings with the pinned original message and check required conflict/override evidence. Compare issue categories independently of explanatory prose. Purpose exact wording is part of the scalar score; faithful alternative wording can still be factually correct.','',
        'Factual-error review is separate: a reviewer records correct/incorrect/unassessed, an exact source quotation and rationale. Do not turn a wording mismatch into a factual-error claim or exclude unreviewed items. Report unsupported/wrong/omitted facts, mishandled corrections/conflicts and fabricated quotations with expected/actual/source. The comparator tests include authored faithful and false summaries; these test verdicts are not live observations.','',
        '## Observed configuration and results','',
        f'- Origin: **mock**, saved fixture model `mock-model`; response sources: {report["response_sources"]}.',
        '- Configuration: `MockProvider(tests/mock_responses)`, original filename/hash/operation manifest matching, current prompt/schema/implementation/policy fingerprints retained per record; policy `materials/office-policy.md`.',
        f'- Exact scalar matches: **{report["scalar_matches"]}/{report["scalar_total"]}**.',
        f'- Route-field matches: **{report["route_matches"]}/{report["route_total"]}**.',
        f'- Structural/quote/issue findings: {len(report["structural_errors"])}/{len(report["quote_errors"])}/{len(report["issue_errors"])}.',
        f'- Purpose factual review: {report["purpose_review"]["correct"]} correct, {report["purpose_review"]["incorrect"]} incorrect, **{report["purpose_review"]["unassessed"]} unassessed** of 21; no live factual accuracy is claimed.',
        '- No live provider observation was made. Supported live adapter settings and redacted requests are in `request-evidence.json`; mock agreement does not establish performance on fresh live wording.',
        '- Machine-readable observed comparison: `planning/accuracy-run.json`. No mismatches were repaired by copying actual outputs into expectations.','',
        '## Expected facts for every message','',
        'The linked oracle for each row contains **all 14 schema properties**, exact supporting quotes, explanatory issues, original source text/hash and the verbatim reviewed source/policy evidence. Scalar expectations are repeated below for inspection.','',
        '| Document | Expected scalar facts | Expected route | Full expectation and source evidence |',
        '|---|---|---|---|']
    for e in expectations:
        scalars={k:v for k,v in e['extraction'].items() if k not in ('issues','supporting_quotes')}
        accuracy.append(f'| {e["document_id"]} | `{json.dumps(scalars,ensure_ascii=False)}` | {e["status"]} / {e["owner"]} / {e["next_action"]} | [Oracle](../tests/expected/{e["document_id"]}) |')
    (deliverables/'accuracy.md').write_text('\n'.join(accuracy)+'\n')
    run_path=ROOT/'planning/test-run.txt'
    run=run_path.read_text() if run_path.exists() else ''
    match=re.search(r'^Ran (\d+) tests in (.+)$',run,re.M)
    green=bool(re.search(r'^OK$',run,re.M)) and 'FAILED (' not in run
    observation=f'{match.group(1)} tests; {"OK" if green else "not passing"}' if match else 'Final full-suite capture pending'
    smoke_path=ROOT/'planning/http-smoke.json'
    smoke=json.loads(smoke_path.read_text()) if smoke_path.exists() else None
    verification=f'''# Verification evidence

## Reproduce

```bash
env -u API_KEY .venv/bin/python -m unittest discover -s tests -v
env -u API_KEY .venv/bin/python -m unittest discover -s tests -v > planning/test-run.txt 2>&1
node --check access_intake/web/app.js
.venv/bin/python -m access_intake intake materials/requests --provider mock
.venv/bin/python -m access_intake intake tests/inputs --provider mock
.venv/bin/python -m access_intake export --output deliverables
.venv/bin/python -m access_intake accuracy --expected tests/expected --actual deliverables/extractions.jsonl
```

The full suite's saved observation is **{observation}**, in `planning/test-run.txt`.
Tests block networking and API_KEY reads, including CLI subprocesses, and use
saved replies under `tests/mock_responses/`. Expected facts predate application
execution and are sourced from the plan/messages/policy; no actual-result acceptance
or automatic expected-value rewriting is used.

## Intended comparisons and assertions

- T01-T03: exact saved mock matching, source-byte hashes, filename identity, malformed
  inputs, metadata versus facts, all required schema properties/types/enums/arrays,
  and exact decoded-message quotes.
- T04-T16/T37-T39: five policy routes in order, complete/missing/conflicting/relative
  facts, requested new permissions, explicit corrections, identifier mismatch,
  reversed dates, withdrawals, actual versus quoted attacks and unusable values.
- T17-T21: injected real-adapter requests for both operations; missing credentials,
  malformed output, HTTP/connection error, refusal, incomplete output, timeout,
  redaction and per-call provenance. No live provider is contacted.
- T22-T26: unchanged reuse, absent-batch retention, changed-source history,
  failed retry after success, producing configuration/policy and source refresh.
- T27-T30 plus the two-process test: accepted-revision ordering in either completion
  order, same-document overlap, claim expiry/heartbeat/fencing, slow-response
  isolation, bounded call deadlines, manual retry and matched snapshot publication.
- T31/T32/T40/T41: guarded CLI workflow, 200-word message, background service intake,
  original-byte upload, inspection/history/retry/resume, served web assets and safe
  text rendering. The service and CLI share SQLite records.
- T33-T36: paraphrase, all 20 source oracles, fixed denominators, faithful-summary
  versus factual-error reporting and fresh-workspace documented workflow.

## Observed HTTP and artifact checks

Local mock-only HTTP smoke: **{'passed' if smoke else 'not yet recorded'}**;
`planning/http-smoke.json` records exact checks and counts. Run a disposable mock
service on port 8765, then `.venv/bin/python tools/check_http.py --port 8765` as
documented in README. This separate smoke checks real loopback HTTP, not a model
service. Final mock comparison observed {report['scalar_matches']}/{report['scalar_total']}
scalar fields and {report['route_matches']}/{report['route_total']} route fields matching;
the 21 manual purpose-review verdicts remain unassessed. Browser automation was
unavailable: JS syntax and served assets were checked, but visual layout and
browser interaction are not claimed as verified.

## Operating assumptions and limits

Four workers share one local-host SQLite store; each model call has a 60-second
caller deadline, with a 180-second lease and 30-second heartbeat. At most four
underlying transports per Intake instance can remain outstanding. Timed-out calls
may finish later; they do not publish results. A process crash can duplicate a
provider call. Recovery assertions use injected claim expiry and stale fencing,
not a hardware/power-loss experiment. Independent processes were exercised against
the same database; no multi-host/network-filesystem guarantee is claimed.

200-400 daily messages and a roughly 2,000-message burst are source workload context,
not a measured latency/cost/throughput SLA. Verification uses small deterministic
fault scenarios, all 20 supplied messages, one paraphrase and a 200-word variant;
there is no live 2,000-message benchmark. HTTP/body/browser upload limits are in
README. Snapshots require quiescent current work; live inspection remains available.
Future semantic policy changes need reviewed router/expectation updates plus refresh.
Model aliases may change behind an unchanged configured ID; actual returned IDs are
recorded when available, not assumed immutable. Mock tests do not prove semantic
classification accuracy on arbitrary unseen messages.

## Observed setup adjustments, repairs and history

Python venv setup initially lacked ensurepip; uv installed the pinned validator
dependencies into the project venv. Sandbox network restrictions required approval
for the dependency download and local HTTP server/client checks. No live model
credentials were used. A test initially imported the app's required-field constant;
it was changed to state all eleven source-defined facts independently. Offline
guards were expanded to reject environment-key reads and network attempts. Caller
deadlines include capacity-wait time. These are identified repairs, not hidden
changes to expected facts.

Final inspection added saved fixtures for completed envelopes carrying an error
and completed envelopes without a model ID. Both exposed missing validation; the
pipeline now rejects them before using data. The failing evidence is saved in
`planning/test-first/response-envelope-repair-red.txt`. A further state test confirms
that a failed changed source never borrows the old successful extraction under its
new hash; that behavior already passed and was not made to fail artificially.
Synthetic omission fixtures were tightened to remove an entire single-fact clause
rather than leaving another purpose sentence behind. A minimal withdrawal/override
fixture no longer carries absent requester/access facts. These expectations still
come from authored source text, not actual outputs. The fixture-authoring helper
deduplicates its manifest so repeated authoring does not change unchanged fixtures.

Saved stage red/green runs are under `planning/test-first/`. Some later tests already
passed because earlier steps implemented their prerequisite behavior; their recorded
runs retain that fact rather than manufacturing failures. Steps 1-3 existed before
the user added per-step stop/commit instructions; the user later requested finishing
all remaining steps. No per-step test-first Git commits were made, and no such
history is claimed. Final commit capture pairing, push and Classroom submission are
not completed by these local checks.
'''
    (deliverables/'verification.md').write_text(verification)
    spec_lines=[line.split('|') for line in (ROOT/'planning/spec.md').read_text().splitlines() if re.match(r'\| R-\d+ \|',line)]
    coverage={parts[1].strip():parts for line in (ROOT/'planning/plan.md').read_text().splitlines()
              if re.match(r'\| R-\d+ \|',line) for parts in [line.split('|')]}
    exceptions={'R-14':'Final submitted commit/session pairing does not exist yet; enabled capture alone is insufficient.',
                'R-15':'Application changes and outputs have not been committed/pushed to the remote default branch.',
                'R-16':'Classroom assignment destination/submission was not supplied or performed.'}
    lines=['# Requirement-by-requirement validation','',
           'Agent-produced evidence assessment for operator review. Marks concern the supplied policy and documented local operating assumptions, not live model accuracy. Open each cited artifact/test before accepting a mark. Final submission requirements remain explicitly not met.','',
           '| Spec line | Requirement | Met or not met | Evidence | Note |','|---|---|---|---|---|']
    met=0
    for parts in spec_lines:
        rid,requirement=parts[1].strip(),parts[2].strip()
        refs=re.findall(r'T-\d+', ' '.join(coverage[rid][2:]))
        evidence=[]
        all_present=True
        for test in dict.fromkeys(refs):
            needle='test_'+test.replace('-','')+'_'
            found=next(((n,line) for n,line in enumerate(run.splitlines(),1) if needle in line and line.endswith(' ... ok')),None)
            if found: evidence.append(f'[{test}](test-run.txt#L{found[0]})')
            else: all_present=False
        note=exceptions.get(rid,'')
        mark='met' if green and all_present and rid not in exceptions else 'not met'
        if mark=='met': met+=1
        if not note:
            note='Within documented mock/local-host verification limits; live semantic accuracy is not inferred.'
            if mark!='met': note='Final passing evidence is not yet present for all named checks.'
        if not evidence: evidence=['[Verification](../deliverables/verification.md)', '[README](../README.md)']
        if rid in ('R-04','R-05','R-12','R-13','R-17','R-29','R-40','R-63','R-70'):
            evidence.append('[Inspection/evidence](../deliverables/verification.md)')
        lines.append(f'| {rid} | {requirement} | {mark} | {", ".join(evidence)} | {note} |')
    lines+=['',f'Count: **{met} met; {len(spec_lines)-met} not met; {len(spec_lines)} total**.','',
            'Test-first red/green logs support sequence observations, not nonexistent commits. Browser interaction, live provider access and final submission are not claimed.']
    (ROOT/'planning/validation.md').write_text('\n'.join(lines)+'\n')


if __name__=='__main__': main()
