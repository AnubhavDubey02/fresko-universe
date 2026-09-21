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
Live tests in `test_f2_corrective.py` are included by the pinned app-wide runner.
They assert persisted values after real commits/rollbacks, rather than just SQL
text or mock call counts. Exact-SHA pinned bench results must be recorded after
CI completes; local smoke is not a substitute for that gate.

CHA exemption and recoverable amount remain PENDING pending shipment-specific
receipts/exemption evidence; approximately INR 80,000 is user-reported, not
independently verified. Broader FSEC findings are not closed by this narrow pass.
