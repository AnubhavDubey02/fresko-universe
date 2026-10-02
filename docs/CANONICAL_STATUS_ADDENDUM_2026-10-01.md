# Canonical status addendum — 2026-10-01

**Status:** Current dated correction and stabilization checkpoint

**Scope:** PR #7 (`codex/integration-stabilization`) and the temporal interpretation of real-world acceptance examples

## How this addendum applies

This document adds current status without rewriting the historical Phase 1, Phase 2, readiness, security, or source-review documents. Where an older document describes one of the cases below as if it were an eternal current fact, this dated addendum controls the current interpretation. The original text remains evidence of what was understood at its recorded time.

Documents are context, not executable truth. Current code, persisted source evidence, authorized business classification, migrations, and reproducible exact-SHA tests remain controlling.

## Latest exact-head stabilization evidence

- Branch: `codex/integration-stabilization`
- Pull request: https://github.com/AnubhavDubey02/fresko-universe/pull/7
- Exact head: `313d275c37e051f2e57d2e731e7cf5add4d72694`
- Exact-head run: https://github.com/AnubhavDubey02/fresko-universe/actions/runs/36869705722
- Result: smoke/readiness passed; pinned Frappe/ERPNext/MariaDB Bench install, migrate, tests, Phase 1-to-current migration proof, second idempotence migration, and concurrency regressions passed.

This exact-head result supersedes handoff wording that treated `0d30a139cfe7f5945e73ef8ed8c6650e0db8d1e6` as the latest verified checkpoint. A later commit still requires its own checks before it can be described as exact-head green.

No merge, retarget, predecessor-PR closure, or Phase 2A implementation is authorized by this addendum.

## Temporal interpretation of real-world acceptance examples

The numbered examples below are business-supplied inputs for future acceptance coverage. They are not implemented Phase 2A behavior, independently verified live balances, or cases in the repository's current 19-case WhatsApp readiness corpus. The readiness corpus validates analogous fail-closed semantics but must not be cited as executable proof of these exact quantities or amounts.

Real-world examples represent facts or classifications at a stated evidence time. They are not timeless current balances. Later evidence creates a later assertion or state transition; it must not erase, mutate, or silently reinterpret the earlier source-backed state.

### 447 Plum crates

The 447 unpriced Plum crates are a historical intermediate state proving that physical Outward must be recordable before price is known. Future Phase 2A acceptance must represent that historical movement with `rate = null` and deterministically open `OUTWARD_UNPRICED`. This example must not be presented as proof that an Outward record already exists or that the crates remain unpriced today.

### 180 Grapes crates

The 180 unpriced Grapes crates are also a historical intermediate state. Later authorized rates exist for the final 180. The earlier unpriced state must remain reproducible, and the later price must be represented by a source-backed authorized assertion with its own effective/evidence time. Do not backfill the later rate into the earlier physical movement or invent a rate value not present in repository evidence.

### INR 101 classification

INR 101 is now classified as labour-related. It must not enter customer/Sohail collections, receipt totals, customer allocation, or cleared-collection reporting. Preserve it as a payment-classification and ledger-boundary case with the classification source and effective time; do not describe it merely as an unidentified or missing customer receipt.

### INR 350,000 Authorization InProcess

`Authorization InProcess` means pending only at the evidence time that reports that state. That evidence must not enter cleared collections or allocation. A later clearance may be recorded only from later source evidence as a new state/assertion; never infer clearance from elapsed time, business expectation, or a later spreadsheet total.

### Other numeric fixtures

- `92 × INR 700 = INR 64,400` remains provisional unless the rate and commercial mapping are supported by authorized evidence at the relevant time. Preserve raw strings such as `Balance Sale`, `BALANCE / UNMAPPED`, and `NOT AVAILABLE`.
- Declared shipping quantity 3,060 versus operating inward 3,056 remains a four-unit comparison between two named bases. It blocks reconciliation for that comparison until source-backed resolution; it is not permission to overwrite either basis.

## Consequences for Phase 2A and later slices

- `Fresko Field Assertion` must carry source provenance and temporal meaning sufficient to preserve earlier and later assertions without destructive overwrite.
- Physical Outward remains independent of Deal, buyer, and rate.
- An unpriced Outward is valid physical truth and opens deterministic commercial exceptions.
- Posted physical facts are corrected by supersession or compensating reversal, never mutation.
- `Fresko Deal.dispatched_qty` remains compatibility-only and is never the physical ledger.
- Collection and Payment Allocation reporting must filter by classification and evidence state; labour-related amounts cannot enter customer collections.
- Point-in-time reports must use only evidence available/effective at that time. Current-state reports may incorporate later evidence while retaining the earlier audit trail.

## Known unknowns

- This addendum does not encode or verify the numeric value, source document, or effective time of the later authorized Grapes rate. Phase 2A must not invent them.
- This addendum does not claim that INR 350,000 later cleared. That remains UNKNOWN until source evidence establishes it.
- Production capture still requires the corresponding source/evidence reference and authorized actor; this dated business correction is not a substitute for transaction-level provenance.
