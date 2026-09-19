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

1. **Source:** exact export location and a bounded, explicitly labelled source
   summary. `source_summary` is reviewer-condensed text, not a verbatim quote;
   use the immutable archive and line ranges or workbook row to read the original.
2. **Interpretation:** what a reviewer thinks the source may mean.
3. **Confirmed facts:** only facts directly supported by the referenced source.
4. **Expected result:** the fail-closed state, exceptions, and independently
   reviewed confidence/status fields.

`extraction_confidence`, `identity_match_confidence`, and
`financial_verification` are separate. They use categorical values defined in
`cases.json`; no percentages are invented. A perfect text extraction can still
have `UNKNOWN` buyer identity and `PENDING` financial verification.

## Message and attachment identity

The uniqueness scope selected for future FSEC-005 implementation on 2026-09-18 is:

`(provider, provider_account_id, conversation_id, provider_message_id)`

- All four values are transport identifiers, not parsed message text. Preserve
  opaque IDs exactly: no case folding, whitespace trimming, or guessed missing
  components. A provider message ID is not assumed globally unique across providers
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

**Design decision (2026-09-18; implementation PENDING):** retain the four original
scope fields and use a unique canonical scoped-message key. Version 1 hashes the
UTF-8 bytes of the compact JSON array
`["fresko-message-v1", provider, provider_account_id, conversation_id, provider_message_id]`
using SHA-256 (no insignificant spaces; literal Unicode; no Unicode normalization).
Provider is a Fresko-controlled adapter identifier; all components must be
non-empty strings. A duplicate key must also match all four stored scope fields;
a mismatch is an integrity conflict, never a merge. Missing scope leaves identity
`UNKNOWN` and must not create a guessed transport key. Historical export locators
are separate evidence provenance, not provider message IDs.

This avoids a potentially oversized composite database index while retaining
original identifiers for audit and collision checks. Global uniqueness on bare
`message_id` is not approved. Database uniqueness, concurrent insert recovery, and
legacy-row migration remain unimplemented FSEC-005 gates. Do not retroactively
deduplicate historical rows without source identity evidence.

Attachment uniqueness uses the parent key plus provider attachment ID, or a
stable ordinal only when the adapter guarantees stable ordering. If neither is
available, attachment identity stays `UNKNOWN`. Same-key conflicting payloads
must preserve both deliveries for review, not silently overwrite the first.

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

FSEC-004 design: store byte SHA-256, byte count, algorithm/version, durable object
reference, and attempt outcome. Readback must match byte count and hash. Hash the
bytes, never the URL/path. Mere presence in an export ZIP is not proof of a
completed future capture workflow. Whole-message attachment completion requires
all expected attachments; any partial item leaves it pending.

A partial or interrupted download records its attempt and remains unsuccessful.
Retry is idempotent against the same scoped message and attachment identity; a
retry must not create another Deal or count another payment.

## Financial and operational boundaries

- `Authorization InProcess` remains `PENDING`, not received or cleared.
- `ledger_received=false` forbids posting a cleared receipt from this evidence;
  it does not prove that money never arrived. Settlement remains `UNKNOWN`.
- A repeated payment reference is a duplicate candidate, not a globally unique
  transaction key. Bank/account scope and settlement evidence are required before
  financial deduplication or posting; preserve both source records meanwhile.
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
