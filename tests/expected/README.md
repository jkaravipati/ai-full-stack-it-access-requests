# Expected-fact provenance

These expectations are authored from the messages and office policy represented
in `planning/plan.md`, not copied from application output or a model run.

- `IT-001.json` through `IT-020.json` correspond to ledger entries E01–E20 in
  `planning/plan.md`. Each expected record contains the original ledger row as
  `source_evidence`, including message quotations and its policy routing rule.
- `IT-P01.json` corresponds to the authored P01 message and E21. Its expected
  request ID, dates, people, purpose and staging/read route are stated in the plan.
- `tools/build_fixtures.py` materializes those reviewed expectations from the
  ledger, input exports and supplied schema. It does not import the application,
  run intake, call a provider or read extraction deliverables. Expected files and
  mock replies are separate artifacts; the app never reads this directory.
- Synthetic edge-case assertions come from T-37–T-39 and the user-confirmed
  interpretations P-1–P-3. The authored input variants and saved mock replies are
  created by `tools/build_edge_fixtures.py` without running application code.

| Tests | Independent source for expectations |
|---|---|
| T-01 | Plan's mock-provider contract: saved reply, mock origin and one call |
| T-02 | Supplied schema: required keys, nullable types, enums and arrays |
| T-03 | Original input bytes, standard SHA-256, decoded message and plan's input/evidence rules |
| T-04–T-16 | E01–E20 message facts and the five ordered office-policy rules |
| T-17 | Plan D-5's exact request defaults and D-4's separate operation contracts |
| T-18–T-21 | Plan's malformed/error/refusal/interruption cases and policy's null-extraction error route |
| T-37–T-39 | Authored source amendments, P-1–P-3 and the existing ordered routing rules |

T-14 deliberately states all eleven required new/change facts independently of
the application's required-field constant. Changes to application code cannot
silently remove a required-fact test case.

Assertions inspect actual application results, but their expected business facts
and routes are fixed before running the application. A discrepancy requires
checking the source/plan; it is not a reason to overwrite expectations with actual
results. No automatic snapshot acceptance is used.

Passing mock tests demonstrates validation and routing behavior, not live model
extraction accuracy. Tests for later build steps have not yet been written.
