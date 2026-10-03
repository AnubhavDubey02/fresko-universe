# Fresko Operations Workspace (`/app/fresko-workspace`)

## Overview
The Fresko Operations Workspace is an internal Frappe Desk page (`Page` doctype) providing internal operators (Salespersons, Accounts, Approvers, and System Managers) with real-time, deterministic commercial reconciliation projections, multi-lot sale creation, rate workflows, physical-to-commercial outward allocations, and buyer alias resolution.

Built natively into the standard Frappe v15 framework, the workspace strictly interfaces with the authenticated public facade (`fresko_universe.commercial.*`) without introducing separate frontend build stacks or modifying existing database schemas.

---

## Key Architectural Principles

### 1. Deterministic Backend Projections Only
- The browser **never** performs financial arithmetic or calculates inventory totals. All quantitative balances (e.g., `totals_by_uom`, `confirmed_value_by_currency`, `remaining_qty`, `unresolved_buyer_count`) are supplied by `fresko_universe.commercial.get_container_reconciliation`, `get_sale_as_of`, and `get_outward_reconciliation`.
- Missing or pending values are rendered explicitly as `PENDING / UNKNOWN` and **never** defaulted or coerced to `0` or `0.00`.

### 2. Strict Role-Aware UX with Server-Side Enforcement
- Page access is guarded by Frappe `Page` roles (`Fresko Salesperson`, `Fresko Accounts`, `Fresko Approver`, `System Manager`). Guest and Supplier access is denied server-side with `PermissionError`.
- **Prepare Authorization**: Commercial sales may be prepared only by users holding the `Fresko Salesperson` role. Technical visibility for `System Manager` does not permit preparing sales without the explicit canonical business role.
- **Verification & Approval**: Verification actions (`verify_sale`, `verify_sale_outward_allocation`, `verify_alias_mapping`) are restricted strictly to `Fresko Accounts`. Approval actions (`approve_sale`, `approve_sale_outward_allocation`, `approve_alias_mapping`) are restricted strictly to `Fresko Approver`.
- Client button visibility is advisory only; server authorization is strictly enforced on all public facade endpoints.

### 3. Native DOM Safety & Raw Alias Integrity
- All untrusted text strings (user names, raw aliases, notes) are rendered via `textContent` or escaped safely to prevent XSS.
- Raw buyer aliases retain exact whitespace and formatting via `white-space: pre-wrap; font-family: monospace;`.

### 4. Asynchronous Stale Response Sequence Guard
- When changing containers or as-of timestamps, asynchronous responses are tagged with an incrementing `load_sequence`. Any slower, out-of-order response whose sequence does not match the active sequence is immediately discarded.

---

## Workspace Features & Tabs

### 1. Container Overview
- **Header Banner**: Current container ID, as-of cutoff timestamp, authorization scope (`INTERNAL` vs `ASSIGNED`), and overall container reconciliation state (`CONFIRMED` or `PENDING`).
- **Exceptions & Unresolved Badges**: Visual indicators for exceptions (`ALIAS_UNRESOLVED`, `RATE_UNKNOWN`, `PRICE_BUCKET_UNALLOCATED`, `LOT_UNKNOWN`, `OUTWARD_WITHOUT_SALE`) alongside unresolved counts.
- **Quantities by UOM Table**: Explicit breakdown of physical, sold, allocated, unallocated, priced, and unpriced quantities grouped by measurement unit.
- **Confirmed Value**: Fully verified and approved commercial value by currency.
- **Money Extension Point**: Reserved interface card documenting the future money ledger reconciliation extension boundary.

### 2. Commercial Sales Tab
- **Reconciled Sales List**: Displays all commercial sales with effective cutoff status, movement evidence state, buyer alias status, and total known amount.
- **Inspect Sale Detail**: View individual sale lines, price status, allocation state, and linked physical outwards.
- **Lifecycle Actions**: `Submit`, `Verify`, `Approve`, and `Reject` (with reason capture), guarded by `expected_version`.
- **Rate Proposal**: Direct rate proposal dialog for unpriced or proposed lines.

### 3. Physical Outwards Tab
- **Outwards List**: Lists posted physical outward movements for the container.
- **Outward Reconciliation Detail**: Line-by-line physical vs. commercially allocated and remaining quantities.
- **Linked Sales**: View sales referencing this outward movement.
- **Allocation Action**: Trigger sale-outward allocation directly from outward context.

### 4. Party Alias Review Queue Tab
- **Exact Alias Queue**: Inspect unmapped raw buyer text with preserved whitespace, proposed customer link, evidence, and submitter.
- **Verification Workflow**: Verify, Approve, or Reject candidate mappings using versioned facade calls.
- **Propose New Alias**: Standard dialog to propose customer mappings.

### 5. Multi-Lot Sale Preparation Dialog
- Structured multi-line lot entry without raw JSON textboxes.
- Supports multi-lot selection from container lots. Lot state defaults to `UNKNOWN` until the operator asserts an actual raw lot or selects a mapped container lot.
- Item and UOM are derived from container metadata and selected container lot; no invented fallback (`BOX`) is inserted.
- Quantity and Rate inputs validate strictly using decimal regex (`is_positive_decimal_string` / `is_valid_decimal_string`), preventing exponential notation (`1e5`) and trailing alphanumeric junk while sending exact decimal strings to backend authority.
- **Rate Basis & Price Bucket**: Selecting `PRICE_BUCKET` requires and displays an explicit `Bucket Key` field; `RATE_ASSERTION` uses line-level rate assertion; `NONE` preserves unpriced status.
- Raw buyer party alias is captured straight from the input element with exact whitespace preserved.
- Source Event ID is an automatically generated UUID per dialog instance, hidden from user and preserved across submission retries.

### 6. Allocation Lifecycle & Review Queue
- Selected Sale view embeds a full **Allocation Review Queue** querying `Fresko Sale Outward Allocation` records via `frappe.client.get_list` across all lifecycle states (`PROPOSED`, `VERIFIED`, `APPROVED`, `REJECTED`, `REVERSED`).
- Operators with `can_verify` (`Fresko Accounts`) can verify proposed records; operators with `can_approve` (`Fresko Approver`) can approve verified records.
- Approved allocations can be reversed via `reverse_sale_outward_allocation`, which strictly requires a non-empty `reason` and evidence link (`Fresko Evidence`), preventing ad-hoc DocType form mutations and cleanly separating physical allocation reversal from banking/money ledgers.
- Propose Allocation dialog utilizes permission-checked projections (`get_sale_as_of` and `get_outward_reconciliation`) to present real opaque line keys and meaningful item/lot/quantity/remaining labels, synchronizes and enforces matching UOM, captures quantity as decimal string (up to 6 decimal places, no Floats), and protects against stale asynchronous response races.

---

## Extensions & Future Boundaries

### Money Reconciliation Boundary
The workspace reserves a dedicated extension card in the Container Overview. Financial transaction matching, bank ledgers, and settlement projections are strictly deferred until root provides the settled money reconciliation contract.

### AskFresko Boundary
Future deterministic navigation and automated anomaly explanation tools can be wired into the workspace without altering existing commercial services or embedding external model keys.

---

## Test Execution Runbook for Root

### Verification & Test Runbook (Root Authority Notice)

> [!NOTE]
> The Node.js offline harness (`scripts/test_workspace_ui.cjs`) verifies syntax, logic contracts, VM-isolated function execution, and UI dialog configurations offline. It is **not** a substitute for browser proof or multi-user live environment verification. Multi-tenant integration tests and browser execution remain **verification pending root runs**.

To execute tests in the environment when root runs verification:

1. **Python Contract & Facade Signatures Test**:
   ```bash
   python -m unittest fresko_universe/tests/test_workspace_contract.py
   ```

2. **Offline UI Logic & State Tests (Node.js)**:
   ```bash
   node scripts/test_workspace_ui.cjs
   ```

3. **Python Bytecode Compilation Check**:
   ```bash
   python -m compileall fresko_universe/fresko_universe/fresko_core/page/fresko_workspace/
   ```

---


The Accounts/Approver-only Money Page at `/app/fresko-money` adds Collection capture, review queues for all four money roots, explicit Container-unapplied/Sale allocations, noncash adjustment/application proposals, correction/reversal actions, and authoritative receipt/receivable queries. Evidence controls reference Fresko Evidence; declared cash permits an optional slip. A Money link appears in the operations Page for financial roles. Server workflow/permissions govern acceptance. Pages use the existing Frappe stack; offline harnesses do not establish browser/mobile usability. Initial live browser verification remains pending.

Ask Fresko currently exposes a fixed authenticated read-tool catalog and strict argument dispatch in `fresko_universe.ask_fresko`. It has no live model/provider or mutation tools. Financial tools require Accounts or Approver roles; supplier roles are rejected before grants.
