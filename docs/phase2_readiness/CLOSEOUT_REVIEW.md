# Phase 1 closeout and readiness review

Date: 2026-09-18. Reviewer: Codex, under Anubhav's delegated technical authority.
This is a source/contract review, not an independent human business sign-off.

## Verified baseline

Remote and local branch both resolved to
`4280451a2225aeedb2c83144471d35c59825636c` before edits. PR #2 was open and unmerged.
Exact-SHA PR and push CI passed; job logs report 78 smoke and 81 bench tests,
with no failures or test skips reported, plus 19 validated fixtures. See
`docs/GATE2_CI_RESULT.md` for immutable run/job references.

The external ZIP's size, SHA-256, integrity, members, and referenced transcript
ranges were revalidated against `manifest.json`. All WhatsApp fixture ranges were
read from `_chat.txt`; workbook cases were checked against Sale Sheet rows 64 and
67 using the archived XLSX XML. No provider IDs or cleared-payment evidence were
inferred. The full archive remains outside Git.

## Review outcome and corrections

| Area / cases | Reviewed expectation |
|---|---|
| Redelivery, identical order text, repeated payment reference | Message identity, buyer identity, and payment identity are separate. A redelivery does not confirm a buyer. Repeated payment reference requires scoped transaction review before posting. |
| Multi-attachment message and equal-timestamp attachment records | Preserve multiple attachment occurrences. Equal timestamps do not establish message grouping. Archive presence does not prove the future capture pipeline succeeded. |
| Add 10 / Add 50 | Quantity and lot are explicit; parent order remains UNKNOWN. No adjacency-based match. |
| Missing rate and multi-lot order | Keep rates UNKNOWN and buyer unresolved. Lot quantities 5 + 10 match the source total 15; that does not approve an order. |
| HOLD/outward and By hand | Reported conflict does not prove physical dispatch. By hand is a mode; GP matching remains pending. |
| Buyer AU candidate and sale/outward date mismatch | Workbook explicitly says NAME / DATE CHECK or DATE CHECK. Preserve candidate status and separate dates. |
| Plum-first allocation and Authorization InProcess | Category allocation order is confirmed in the conversation, not receipt splits or bank settlement. Settlement remains UNKNOWN; verification PENDING. |
| Missing cold-storage bill | Verified expense UNKNOWN; any display zero is provisional. |
| CHA claim | Approximately INR 80,000 is reported, not verified. Shipment receipts, exemptions, and recoverable amount remain PENDING. |
| Partial download and correction/rejected match | Contract scenarios, not observed incidents. Incomplete capture cannot succeed; source and rejected candidates remain auditable. |

The old `raw_text` fields were condensed summaries, sometimes including reviewer
interpretation. They are now explicitly `source_summary`; authoritative originals
remain at the archive locators. Review labels mean Codex reviewed the expected
contract, not that the business identity, amount, or transaction was verified.

The fixture validator checks structure and selected fail-closed invariants.
Archive validation verifies bytes and locator existence, not semantic equivalence
of every summary or correctness of a future extractor. Source comparison above
is a separate manual review. Six adversarial contract tests now reject misleading
source labels, invented amendment parents, and unsupported certainty promotions.

## Technical choices resolved; implementation still pending

MSG-UNIQ uses a versioned canonical scoped-message key plus original scope fields
and collision checks. FSEC-004 requires byte hashing and storage readback before
capture. The complete rules are in `WHATSAPP_FIXTURE_CONTRACT.md`.

Future implementation acceptance tests must cover concurrent redelivery,
distinct known provider IDs with identical text, cross-account ID reuse,
conflicting payloads on one key, ambiguous attachment order, interrupted writes,
hash mismatch, retries, and append-only human corrections. The current corpus
does not execute these future workflows; FSEC-004 and FSEC-005 remain OPEN.

## Information to collect when operational resolution is needed

- Explicit parent-order references for ambiguous amendments.
- Customer-master evidence and human acceptance/rejection for buyer candidates.
- Original GP/DO evidence for physical dispatch disputes.
- Cleared bank entries and scoped receipt allocation for payment reconciliation.
- Cold-storage invoices; shipment-specific CHA receipts and exemption evidence.

These gaps do not block this documentation/fixture closeout. Leave their states
UNKNOWN/PENDING; do not ask the user to guess. Free-first dependency policy stays
locked. No new dependencies, live ingestion, CHA module, or Phase 2 runtime work.

## Reproduction

```bash
python3 scripts/validate_phase2_readiness_fixtures.py
python3 scripts/validate_phase2_readiness_fixtures.py --archive /tmp/fresko-whatsapp-latest.zip
python3 -m unittest discover -s scripts -p 'test_readiness_fixture_contract.py' -v
(cd fresko_universe && python3 -m unittest tests.test_smoke_unit -v)
```

Required remote gate: pinned install, migrate, and bench tests on the resulting
immutable commit, with both workflow conclusions checked before handoff.
