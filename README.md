# Northstar access operations

A runnable Python application with **CLI, HTTP service and browser dashboard** for
turning exported access requests into a durable human-review queue. All three use
the same SQLite records. It prepares requests; approval and access provisioning
remain human work.

The supplied messages are fictional. Default operation uses saved **mock** replies
and needs no API key. A configurable OpenAI Responses integration is implemented;
no live-provider run is claimed by the committed examples.

## Setup

Tested with Python **3.12.3** on Linux; source/package metadata targets Python 3.10+.
Run commands from the repository root. The current workspace already has a prepared
`.venv`. On a fresh checkout, install the exact runtime dependencies with uv:

```bash
uv venv --python python3 .venv
uv pip install --python .venv/bin/python -r requirements.lock
```

Alternatively, on a system with Python's venv/ensurepip installed:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
```

Debian/Ubuntu's optional `python3-venv` package is needed for the latter route;
using uv does not need ensurepip. No npm installation or frontend build is required.

## Web interface and service

```bash
.venv/bin/python -m access_intake serve --provider mock
```

Open **http://127.0.0.1:8000** on the machine running the service. On a remote
workspace, forward port 8000; its loopback address is not automatically your
laptop's loopback address. The service is intentionally local/loopback, without
a public deployment or remote-user authentication system.

The dashboard lets an operator:

- **Start intake** from the configured input folder (`materials/requests` by default).
- **Upload exports** as JSON files, preserving their original bytes through base64 upload.
- Inspect completed results while other messages are pending; search/filter the queue.
- Open request facts, source message, exact quotes, issues, owner and next action.
- Inspect each attempt's **History**, including earlier hashes and failures.
- **Retry extraction**, **Resume unfinished** work and **Export snapshot**.

To select a different shared state, input folder or port:

```bash
.venv/bin/python -m access_intake serve --provider mock --state .state/intake.sqlite3 --input-root materials/requests --output deliverables --port 8000
```

Server startup and its background worker resume queued/expired-running records
using their saved provider configuration. The configured provider applies to NEW
intake; existing records and retries retain their producing configuration. Use a
separate state file to keep mock and live exercises separate.

## CLI

```bash
.venv/bin/python -m access_intake intake materials/requests --provider mock
.venv/bin/python -m access_intake queue
.venv/bin/python -m access_intake inspect IT-006.json
.venv/bin/python -m access_intake history IT-006.json
.venv/bin/python -m access_intake resume
.venv/bin/python -m access_intake retry IT-006.json
.venv/bin/python -m access_intake export --output deliverables
```

Every stateful command accepts `--state <sqlite-file>`. Default:
`.state/intake.sqlite3`. Inspection includes export metadata, source text, hashes,
attempt IDs, producing settings/policy and the exact retry command on failure.
An intake command exits 1 if the current queue contains extraction errors;
needs-information is a successful extraction requiring human clarification.

Run `python3 -m access_intake --help` or a subcommand's `--help` for arguments.

## HTTP API

With the service running, no key or authentication header is needed for these
local mock examples:

```bash
curl -sS http://127.0.0.1:8000/api/queue
curl -sS -X POST -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:8000/api/intake
curl -sS http://127.0.0.1:8000/api/documents/IT-001.json
curl -sS http://127.0.0.1:8000/api/documents/IT-001.json/history
curl -sS -X POST -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:8000/api/documents/IT-001.json/retry
curl -sS -X POST -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:8000/api/resume
curl -sS -X POST -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:8000/api/export
```

Intake/retry/resume return 202 and processing continues in the background. Upload
via `POST /api/intake` with `{"exports":[{"filename":"IT-001.json","data_base64":"..."}]}`.
Filenames must be unique JSON basenames. HTTP bodies are limited to 8 MiB, decoded
files to 128 KiB, and batches to 2,000 files; the browser uses a 5 MiB decoded-batch
limit. Request facts still come exclusively from `message`. No API accepts an
arbitrary server filesystem path. Cross-origin changes and unrecognized Host
headers are rejected; browser rendering uses text nodes for source data.

## Live provider configuration

The only credential environment-variable name is **API_KEY**. Set it in the
process environment using your normal secret mechanism; do not put it in files,
commands committed to Git, logs or provider configuration JSON.

The supported adapter configuration uses OpenAI Responses at
`https://api.openai.com/v1/responses`, model `gpt-5.6-terra`, reasoning effort `none`,
4096 output tokens, strict JSON Schema, no tools, `stream:false` and `store:false`.
Account/model availability has not been live-tested. The configurable fields are
`provider`, `endpoint`, `model`, `reasoning_effort`, `max_output_tokens`, `timeout`.
Only `provider: "openai"` is supported for live mode. Defaults are in
`access_intake/providers.py`; a nonsecret override is accepted with `--config`:

```bash
.venv/bin/python -m access_intake intake materials/requests --provider openai --state .state/live.sqlite3
.venv/bin/python -m access_intake serve --provider openai --state .state/live.sqlite3 --config config.example.json
```

Saved mock replies are matched by document filename, original-byte hash and
operation. New/modified messages need new authored mock fixtures, or live mode;
mock mode never invents a reply from filenames or expected-result files.

## Recovery and shared operation

- Multiple local operator processes share a SQLite file with short transactions.
  Model calls happen outside database transactions; concurrent readers can inspect
  already completed requests. Multi-host/network-filesystem operation is unsupported.
- The latest **accepted** per-document generation wins, regardless of model
  completion order. Superseded responses remain in history, never replacing a newer target.
- Pending replacements show their own source hash and generation with no review
  route; any previous result is labelled reference-only. New failure means the
  current queue shows an error, while older valid results remain in history.
- Unchanged success **or error** is reused on normal intake. Explicit retry forces
  a new attempt; resume processes queued or expired-running work, not terminal errors.
  Missing documents from later batches remain in the queue.
- Default concurrency is four workers (`--workers`), with a 60-second per-call
  deadline, 180-second lease and 30-second heartbeat. There is no automatic provider
  retry/backoff. Rate limits, outages and timeouts are visible failures. At most four
  underlying transports per Intake instance remain outstanding; late timed-out
  transports can hold those slots until they return. A new attempt may duplicate a
  provider call after a process crash, but fencing prevents stale result publication.
- Hashes cover original bytes. Fingerprints also cover relevant provider settings,
  prompts, schemas, implementation version and policy content. Credentials,
  scheduling and timeout settings do not invalidate successful reuse. Retries retain
  saved configuration; use new intake to adopt changed settings.
- Routing implements the supplied five-rule policy in code. A future semantic
  policy change requires reviewing/updating that router and its expectations, then
  refreshing intake. A changed policy hash triggers new attempts; arbitrary prose
  edits do not automatically generate a new routing program.
- Snapshots require no pending current targets. Immutable generations under
  `deliverables/.generations/` contain matching extraction/queue/history/manifest
  files. One `current` symlink publishes the generation. Concurrent export readers
  must resolve `current` once, then read both files from that pinned directory.
  A previously published snapshot remains an as-of view while live state changes.

All human-review statuses and owners follow `materials/office-policy.md`.
Security Review considers risk before forwarding to the system owner; a manager
is a contact, not an approval. Unusable source dates/blank facts become null with
issues, clear replacement wording counts as correction, and quoted/negated attack
discussion is not an override. Candidate attacks receive a separate context check;
its failure produces an extraction error, never an assumed harmless verdict.

## Tests, accuracy and validation

```bash
env -u API_KEY .venv/bin/python -m unittest discover -s tests -v
env -u API_KEY .venv/bin/python -m unittest discover -s tests -v > planning/test-run.txt 2>&1
node --check access_intake/web/app.js
```

Tests use saved responses under `tests/mock_responses/`. Shared guards reject
network/DNS attempts and API_KEY reads; CLI subprocess tests install the same guards.
Provider tests inject a synthetic credential, never read a real one. Expected facts
come from the reviewed plan/source ledger, not application runs; see
`tests/expected/README.md`. Failing and passing stage runs are in `planning/test-first/`.

To reproduce the 21-example mock deliverables and accuracy comparison:

```bash
.venv/bin/python -m access_intake intake materials/requests --provider mock
.venv/bin/python -m access_intake intake tests/inputs --provider mock
.venv/bin/python -m access_intake export --output deliverables
.venv/bin/python -m access_intake accuracy --expected tests/expected --actual deliverables/extractions.jsonl
```

`tests/inputs` is scanned nonrecursively; only the root paraphrase is included in
this accuracy set. Other nested synthetic cases are separate tests. Accuracy counts
252 scalar comparisons and 63 routing comparisons; failed/missing extractions do
not disappear from denominators. Wording-only purpose mismatches are distinct from
source-grounded factual review; unreviewed summaries remain explicitly unassessed.
Mock agreement is not live model accuracy. Details are in `deliverables/accuracy.md`.

For an actual local HTTP check, use a disposable mock state in terminal 1:

```bash
.venv/bin/python -m access_intake serve --provider mock --port 8765 --state .state/http-smoke.sqlite3 --output .state/http-exports
```

Then in terminal 2:

```bash
.venv/bin/python tools/check_http.py --port 8765
```

The checker refuses non-mock services and saves `planning/http-smoke.json`.
It tests local HTTP and assets, not visual browser interaction. Stop the service
with Ctrl+C. The 2,000-message workload is context, not a measured live throughput,
latency, provider-cost or multi-region availability guarantee.

`planning/validation.md` lists each of the 76 spec requirements with evidence and
limits. `deliverables/verification.md` records observations and repairs. Entire
capture may be enabled, but final commit pairing/push/Classroom submission remain
separate actions; no test-first Git history is fabricated for uncommitted work.
