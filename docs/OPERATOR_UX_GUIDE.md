# Fresko Clear — Operator UX Guide & Architecture

## 1. Product Direction & Governing Principles

Fresko Clear is the **Evidence-First Operational Interface for Produce Trade**, designed for real operational actors (traders, accounts managers, and approvers) working under high transaction velocity.

It is founded on four immutable principles:
1. **Action over Navigation:** Proactively surface what demands attention today in a centralized "Needs My Action" feed rather than forcing operators to search technical DocTypes or memorize container identifiers.
2. **Human Meaning over Internal IDs:** Visual prominence is given to Customer Name, Variety, Package Count, and Rate. Technical IDs (`FSALE-2026-00042`) serve strictly as secondary audit anchors in monospace.
3. **Evidence Beside Decisions:** All decisions present linked source evidence (weighment slips, mandi receipts, bank credit references) directly alongside transaction facts in a contextual split pane.
4. **Explicit Non-Zero States:** `PENDING`, `UNKNOWN`, `CONFLICT`, and `BLOCKED` are distinct, explicit states. Unestablished financial amounts **never render as zero**.

---

## 2. Capability Architecture & Session Boot (`bootinfo.fresko`)

Capabilities and landing routes are authoritatively derived on the server and injected into the Desk session via Frappe's `extend_bootinfo` hook.

### 2.1 Hook Lifecycle
- In Frappe v15, `extend_bootinfo` runs after boot-cache resolution (including cache hits), ensuring current user role changes immediately update session capabilities.
- Zero financial aggregates or business transaction counts are stored in boot data, eliminating cross-session cache leaks.

### 2.2 Role & Capability Matrix

| Role | Persona | Default Route | Key Command Capabilities |
|---|---|---|---|
| **Fresko Salesperson** | `salesperson` | `fresko-workspace` | `create_sale`, `supersede_sale`, `propose_rate`, `create_outward`, `submit_outward`, `propose_sale_outward_allocation`, `propose_alias`, `attach_evidence`, `view_evidence` |
| **Fresko Accounts** | `accounts` | `fresko-money` | `verify_sale`, `verify_rate`, `verify_sale_outward_allocation`, `verify_alias`, `capture_collection`, `verify_collection`, `propose_payment_allocation`, `verify_payment_allocation`, `propose_adjustment`, `verify_adjustment`, `resolve_exception` |
| **Fresko Approver** | `approver` | `fresko-workspace` | `approve_sale`, `approve_rate`, `reject_sale`, `post_outward`, `approve_sale_outward_allocation`, `reject_sale_outward_allocation`, `reverse_sale_outward_allocation`, `approve_alias`, `reject_alias`, `approve_collection`, `approve_payment_allocation`, `approve_adjustment` |
| **System Manager** (alone) | `system_manager` | `Workspaces` | `admin_desk`, `view_audit` (standard technical desk; no implicit business permissions) |
| **Supplier Bearing** | `supplier_denied` | `None` | `[]` (immediate denial; internal HTTP routes return HTTP 403) |
| **Non-Operator** | `non_operator` | `None` | `[]` (unauthorized fallback) |

*Multi-Role Union:* Users holding multiple operational roles receive the union of capabilities. Landing route precedence is **Approver** (`fresko-workspace`) > **Accounts** (`fresko-money`) > **Salesperson** (`fresko-workspace`).

---

## 3. Needs My Action Feed Service (`operator_service.py`)

All operator action feeds reside in `fresko_universe.fresko_core.services.operator_service`.

### 3.1 Security & AST Invariants
1. **Zero Raw SQL:** `frappe.db.sql` is strictly prohibited.
2. **Zero `get_all`:** Only `frappe.get_list` is permitted, ensuring Frappe row-level permission query hooks execute automatically.
3. **Zero `ignore_permissions`:** Bypassing permissions is strictly forbidden.
4. **Supplier-First Denial:** Supplier roles are rejected immediately with `frappe.PermissionError`.
5. **Scoped Evidence:** Linked Evidence is authorized individually. If the user lacks read permission on an evidence document, the reference is omitted and returned as `evidence_state: "RESTRICTED"`.

### 3.2 Action Eligibility & Segregation of Duties
Segregation rules are pure functions matching backend service constraints:
- **Maker Cannot Verify:** An operator who prepared or proposed a record (`prepared_by` / `proposed_by`) is barred from verifying it.
- **Maker and Verifier Cannot Approve:** Approvers who previously prepared or verified a record cannot approve it.
- **Rate Revisions:** Rate proposals create superseding Sale revisions; segregation is evaluated against the active revision's actors.
- **Historical Mode:** Historical projections (`as_of` timestamp provided) are strictly read-only (`can_act: False`).

---

## 4. UI Shell & Visual Design System

### 4.1 Desk Chrome Suppression
Desk chrome is suppressed via `fresko_shell.css` scoped strictly to `body.fresko-operator-shell`:
- Search bar, help dropdown, notifications dropdown, sidebar, and breadcrumbs are hidden for operators.
- `System Manager` sessions retain standard Frappe Desk chrome intact.

### 4.2 Reversible Router Guard
`fresko_shell.js` tags `document.body` with `fresko-operator-shell` only when `frappe.boot.fresko.is_operator` is `true`.
- Routes initial blank or Workspaces landing to `fresko.default_route`.
- Scoped per user via `sessionStorage.getItem("fresko_initial_routed_" + frappe.session.user)`.
- Never intercepts browser history, back-button, new tabs, or explicit deep links.

### 4.3 State Vocabulary
- `PENDING`: Surface `#f8fafc`, Border `#cbd5e1`, Text `#475569`
- `UNKNOWN`: Surface `#f1f5f9`, Border `#94a3b8`, Text `#334155`
- `CONFLICT`: Surface `#fef2f2`, Border `#f87171`, Text `#991b1b`
- `BLOCKED`: Surface `#f8fafc`, Border `#e2e8f0`, Text `#64748b`
- `CONFIRMED`: Surface `#f0fdf4`, Border `#86efac`, Text `#166534`
- `VERIFIED`: Surface `#eff6ff`, Border `#93c5fd`, Text `#1e40af`

### 4.4 Mobile Adaptation (390px & 360px)
- Touch targets maintain a minimum computed height of 44px (48px for primary action buttons).
- Soft-keyboard listener dynamically suppresses the fixed mobile navigation bar on input focus.
- Tables collapse into structured touch cards with 0px horizontal root overflow.

### 4.5 Keyboard Accessibility & Split Pane Navigation
- All action feed cards (`.fresko-action-card`) provide semantic interactive roles (`role="button"`, `tabindex="0"`).
- Keyboard activation supports both `Enter` and `Space` to inspect contextual details and linked evidence without triggering form submits.
- Historical mode renders a dedicated "Needs My Action is Live-Only" notice with a "Return to Live" button to seamlessly clear historical cutoff filters.

### 4.6 Navigation Dispatch and State Verification
- Proposing outward allocations dispatches to the `outwards` tab and immediately inspects the targeted outward movement.
- Reviewing allocations validates current record state on the server (`frappe.client.get`) prior to mutation, guarding against concurrent state transitions.
- Collections and payment allocation reviews navigate directly to `fresko-money` with context stored in `sessionStorage`.
- Network failures in the alias review queue render inline error alerts with an idempotent "Retry" trigger.
