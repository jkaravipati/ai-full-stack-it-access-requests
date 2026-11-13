# Verification evidence

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

The full suite's saved observation is **46 tests; OK**, in `planning/test-run.txt`.
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

Local mock-only HTTP smoke: **passed**;
`planning/http-smoke.json` records exact checks and counts. Run a disposable mock
service on port 8765, then `.venv/bin/python tools/check_http.py --port 8765` as
documented in README. This separate smoke checks real loopback HTTP, not a model
service. Final mock comparison observed 252/252
scalar fields and 63/63 route fields matching;
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
