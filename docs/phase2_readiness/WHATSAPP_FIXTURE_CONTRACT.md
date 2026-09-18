# WhatsApp readiness fixture contract

**Status:** reviewed test/planning contract, 2026-09-18

**Implementation boundary:** no live ingestion, webhook, provider integration,
payment posting, stock mutation, automated approval, or CHA module is authorized.

The compact corpus at
`fresko_universe/fresko_universe/fixtures/whatsapp_readiness/` is derived from
the 18-Sep-2026 Drive export recorded in `docs/SOURCES.md`. The full ZIP remains
outside Git. Source excerpts are test evidence, not accounting or inventory
truth.

## Separation required in every case

Every fixture keeps four layers distinct:

1. **Source:** exact export location and a bounded source excerpt.
2. **Interpretation:** what a reviewer thinks the source may mean.
3. **Confirmed facts:** only facts directly supported by the referenced source.
4. **Expected result:** the fail-closed state, exceptions, and independently
   reviewed confidence/status fields.

`extraction_confidence`, `identity_match_confidence`, and
`financial_verification` are separate. They use categorical values defined in
`cases.json`; no percentages are invented. A perfect text extraction can still
have `UNKNOWN` buyer identity and `PENDING` financial verification.

## Message and attachment identity

The proposed uniqueness scope, which must be decided before implementing
FSEC-005, is:

`(provider, provider_account_id, conversation_id, provider_message_id)`

- All four values are normalized transport identifiers, not parsed message
  text. A provider message ID is not assumed globally unique across providers
  or provider accounts.
- Redelivery of the same complete provider-scoped key reuses one Evidence row
  and appends a delivery-attempt record.
- Two different provider message keys containing identical text remain two
  Evidence rows. A content/fingerprint match may open a duplicate candidate; it
  must not silently collapse the records.
- The historical export does not include provider message IDs. Equal text or
  equal displayed timestamps therefore leave message identity `UNKNOWN`.
- One message may own zero, one, or many attachments. Within a message, prefer
  provider attachment ID; otherwise use stable attachment ordinal. A byte hash
  proves content, not message identity, and the same file may be resent.

**Unresolved FSEC-005 design decision:** extend Evidence with the scope fields
and enforce a composite unique key, or store one canonical scoped-message key
and make that key unique. A global unique constraint on the current bare
`message_id` is not approved by this readiness pack.

## Human review and correction

- Raw source and prior interpretations are immutable evidence.
- A correction appends actor, server timestamp, reason, before/after values,
  and source references.
- Accepted and rejected identity candidates remain auditable. Rejection does
  not delete the candidate or source.
- Ambiguous amendments such as “Add 10” keep `parent_order=UNKNOWN` and open
  `AMENDMENT_PARENT_UNRESOLVED`; message adjacency is not a match key.
- A reviewer may resolve a candidate only with an explicit action. Absence of a
  rejection is not acceptance.

## Attachment capture and retry

Recommended state vocabulary for a future design is `PENDING`, `DOWNLOADING`,
`CAPTURED`, `FAILED_RETRYABLE`, `FAILED_PERMANENT`, `PARTIAL`, and
`HASH_MISMATCH`. This document does not implement those states.

An attachment may become `CAPTURED` only after:

1. the transport finishes without truncation;
2. expected byte length matches when the provider supplies one;
3. the SHA-256 of the actual bytes is computed and stored with an algorithm
   version;
4. the durable write completes; and
5. storage readback confirms the stored object.

A partial or interrupted download records its attempt and remains unsuccessful.
Retry is idempotent against the same scoped message and attachment identity; a
retry must not create another Deal or count another payment.

## Financial and operational boundaries

- `Authorization InProcess` remains `PENDING`, not received or cleared.
- A container-level instruction to allocate plum first and grapes second does
  not identify a per-receipt split.
- A missing cold-storage bill leaves the verified amount `UNKNOWN`. A report may
  display a clearly labelled provisional zero, but zero is not stored as truth.
- HOLD versus physical-outward disagreement remains a source conflict until the
  referenced GP/DO evidence is matched.
- “By hand” is a positive dispatch mode, not a missing vehicle.
- CHA exemption eligibility and recoverable amount remain `PENDING` until
  shipment-specific official receipts and exemption evidence are reviewed. The
  approximately ₹80,000 amount is user-reported and not independently verified.

## Validation

Run the self-contained corpus validation:

```bash
python3 scripts/validate_phase2_readiness_fixtures.py
```

When the external ZIP is available, also validate provenance and archive member
references:

```bash
python3 scripts/validate_phase2_readiness_fixtures.py \
  --archive /tmp/fresko-whatsapp-latest.zip
```

The validator uses only the Python standard library. Passing it confirms fixture
shape and source integrity; it does not validate a future ingestion engine.
