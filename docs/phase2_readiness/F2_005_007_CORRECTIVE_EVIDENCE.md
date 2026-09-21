# F2-005/006/007 corrective evidence — 2026-09-21

Scope: corrective work only on draft PR #3, `phase2-evidence-durability`.
Baseline inspected remotely and fetched: `1abd88ae8b02eb290d88663d1f4654191a44b6f9`.
No live ingestion, dependencies, commercial/financial mutation or merge.

## F2-005: receipt semantics and compatibility

`source_sender_id` and `source_sent_at` remain immutable source provenance.
`Evidence.received_at` keeps its database/API name for compatibility, with the
label **First Received At Ingress**. It means the original delivery's established
Fresko ingress receipt time. Neither later receipts nor processing time replace
it; a historical NULL stays NULL. This avoids a column rename and a speculative
timestamp backfill. `Attempt.delivery_received_at` records each delivery's
explicit ingress receipt; `attempt_time` remains the audit recording time.

Different receipt time alone is not a provenance conflict. Sender/send-time
differences remain conflicts. No confidence or missing timestamp is invented.

## F2-006: reproduced before removing the workaround

Before editing the runtime helper, ran
`python3 scripts/reproduce_f2_006_fk_bypass.py` on an isolated MariaDB
10.6.28 container, image digest
`sha256:40153feb479c0da88b5cfe3f50f44c91f7baf05a1b7bcc5beb7eb37a890a8f16`.

The probe uses three small InnoDB tables with real Evidence/Attachment foreign
keys. Connection A inserts the parent entities without committing; connection B
disables FK checks and commits the audit; A rolls back. Actual persisted result:

```text
persisted_attempts=1 missing_evidence=1 missing_attachment=1 after_caller_rollback
```

This is a minimal MariaDB mechanism reproduction, not a claim that Frappe Link
fields necessarily create SQL FKs. The live app regression separately examines
actual DocType metadata and database constraints after schema synchronization.

Chosen design: the attempt's `evidence` and `evidence_attachment` columns retain
their existing values and names but become **Data identifier snapshots**, not
Links or existence claims. Independent attempts can truthfully retain identifiers
of rolled-back creations. No parent is fabricated; no FK checks are disabled.
The app never treats snapshot presence as entity existence. Orphaned-identifier
audit is visible only to Administrator/System Manager; other users must resolve
an existing parent and pass its permissions. No reconciliation or new entity
creation is performed automatically. Historical values are not rewritten.

## F2-007: bounded independent persistence

- One initial try plus at most two retries, delayed 50 ms then 100 ms.
- Retries only for transient connection/interface/lock errors; schema,
  authorization and mismatched duplicates fail closed without repeated writes.
- Each new connection has 2-second connect/read/write timeouts and a 1-second
  InnoDB lock wait timeout. No caller transaction is committed or rolled back.
- Attempt name and write-envelope fingerprint stay fixed through all retries.
  A duplicate succeeds only when the stored fingerprint matches exactly.
  A duplicate name alone is not success. Old NULL fingerprints are not guessed.
- Lost acknowledgement after a real autocommitted INSERT is retried and confirmed
  without another logical audit row. Exhaustion does not claim durable success;
  existing conflict paths continue to fail closed.

## Verification

Local smoke: **123 tests**, no failures/errors/skips. Constants: **14 tests**.
Readiness corpus: **19 fixtures**. Readiness contract: **6 tests**. All passed.
Targeted local retry/access suite: **6 tests**, all passed (included in smoke).

Exact implementation SHA: `f8486921bab12198c8623ce1db36086fbf8f8b44`.
[CI run 35644231347](https://github.com/AnubhavDubey02/fresko-universe/actions/runs/35644231347)
completed successfully on that SHA. Logs independently retrieved using the
authenticated GitHub CLI:

| Gate | Count | Failures | Errors | Skips |
|---|---:|---:|---:|---:|
| CI smoke | 123 tests | 0 | 0 | 0 |
| CI readiness contract | 6 tests | 0 | 0 | 0 |
| CI readiness corpus | 19 fixtures | 0 | 0 | 0 |
| Full pinned Frappe/MariaDB bench | 119 tests | 0 | 0 | 0 |

Smoke job: `106480660477`. Bench job: `106480754663`.
Bench includes **11 live corrective tests** from `test_f2_corrective.py` and ends
with `Ran 119 tests`, `OK`, `==> CI bench OK`. Frappe/ERPNext immutable pins
are unchanged. This is a real fresh-site install + migrate + full app test gate,
not an assertion that a pre-existing production site was upgraded.

Persisted-state output from the bench log:

```text
F2-005 persisted: first=2026-09-19 10:01:00 redelivery=2026-09-19 10:05:00 outcome=SUCCESS_IDEMPOTENT_REDELIVERY
F2-005 historical received_at=NULL remains NULL after later receipt
F2-005 source_sender_id: conflict audit survives rollback; original unchanged
F2-005 source_sent_at: conflict audit survives rollback; original unchanged
F2-006 persisted: attempt=1 canonical_evidence=0 canonical_attachment=0 references=IDENTIFIER_SNAPSHOTS relational_FKs=0 no_parent_fabricated
F2-007 transient: connections=2 persisted_attempts=1 after_caller_rollback
F2-007 exhausted: connections=3 retries=2 conflict_failed_closed=True durable_rows=0
F2-007 ambiguous INSERT committed then acknowledgement lost: rows=1 identical_replay=True mismatched_duplicate=False
F2-007 caller mutation rolled back; independent conflict attempt still committed
```

This document's follow-up evidence commit changes no implementation or tests.
Its own CI result must be checked separately; the run above proves the named
implementation SHA only. PR #3 remains draft and unmerged.

CHA exemption and recoverable amount remain PENDING pending shipment-specific
receipts/exemption evidence; approximately INR 80,000 is user-reported, not
independently verified. Broader FSEC findings are not closed by this narrow pass.
