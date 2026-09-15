# PERMISSION_MATRIX — Roles × DocTypes / sensitive actions

**Tip:** `18c5042`.  
**Legend:** `VERIFIED_IN_CODE` = observed in DocType JSON and/or Python. `DOC_ONLY` = claimed in controls/QA docs but not enforced in app code. `UNKNOWN` = not proven this baseline.

Fresko roles from fixtures: `Fresko Salesperson`, `Fresko Approver`, `Fresko Accounts` (+ platform `System Manager`).

## RECORDED FACTS — DocType CRM permissions (from JSON)

| DocType | System Manager | Fresko Approver | Fresko Accounts | Fresko Salesperson | Evidence |
|---|---|---|---|---|---|
| Fresko Deal | RWCD+share | RWC (no delete) | R | RWC (no delete/export) | `fresko_deal.json` permissions |
| Fresko Container | RWCD+share | RWC | RW | R | `fresko_container.json` |
| Fresko Approval | RC+delete (no write) | RC (no write/delete) | R | R | `fresko_approval.json` |
| Fresko Revision | RC+delete | RC | R | R | `fresko_revision.json` |
| Fresko Evidence | RWCD | RWC | R | RC | `fresko_evidence.json` |
| Fresko Exception | RWCD | RWC | RWC | RC | `fresko_exception.json` |
| Child tables (Lot/Rate Rule/Source Doc) | inherit parent | — | — | — | permissions_count=0 |

`track_changes`: Deal=1, Container=1, Exception=1; Approval=0, Evidence=0, Revision=0 (**VERIFIED_IN_CODE**).

## Sensitive actions

| Action | Salesperson | Approver | Accounts | System Manager | Enforcement | Tag |
|---|---|---|---|---|---|---|
| Create Deal (Proposed) | Yes (RWC) | Yes | No write | Yes | DocType perm + `before_insert` forces Proposed | VERIFIED_IN_CODE |
| `apply_rate_rules` | Callable if logged in | Callable | Callable | Callable | **No role check**; `ignore_permissions` on save | VERIFIED_IN_CODE — gap |
| `approvals.decide` | Denied | Allowed | Denied (unless SM) | Allowed | `get_roles` check | VERIFIED_IN_CODE |
| Oversell override (D10) | Denied | Denied | Denied | Allowed | `OVERSELL_OVERRIDE_ROLES` | VERIFIED_IN_CODE |
| `accept_counter` | Only if owner or `salesperson_user` | Denied (even Approver) | Denied | Denied unless owner/salesperson | Explicit user ACL | VERIFIED_IN_CODE |
| `cancel_deal` | Callable (no ownership check) | Callable | Callable | Callable | Reason required; **no role** | VERIFIED_IN_CODE — gap |
| `record_dispatch` | Callable | Callable | Callable | Callable | Physical ceiling; **no role** | VERIFIED_IN_CODE — gap |
| `request_revision` | Callable | Callable | Callable | Callable | Reason; material needs evidence when locked | VERIFIED_IN_CODE — gap |
| `apply_revision` | Callable | Callable | Callable | Callable | Approval doc must **exist** for material; **no role**; no Approval↔Deal bind | VERIFIED_IN_CODE — gap |
| Desk edit `approved_rate` | Blocked | Blocked | Blocked | Blocked without flag | validate + read_only | VERIFIED_IN_CODE |
| Desk edit `dispatched_qty` | Blocked | Blocked | Blocked | Blocked without flag | validate | VERIFIED_IN_CODE |
| Delete Approval | No | No | No | Yes (on_trash gate) | `fresko_approval.py` | VERIFIED_IN_CODE |
| Edit Approval after insert | No | No | No | No | append-only validate | VERIFIED_IN_CODE |
| `permission_query` row filters | — | — | — | — | **Not implemented** | VERIFIED_IN_CODE (absence) |
| Whitelist validates role (controls claim) | — | — | — | — | controls.md § revision path claims role validation | DOC_ONLY — **contradicted by code** |

## TEST RESULTS

- `test_accept_counter_acl_owner_salesperson_only`, `test_system_manager_cannot_accept`, `test_approver_cannot_accept` (smoke).
- `test_approver_cannot_oversell_override`, `test_d10_oversell_system_manager_only`.
- **No** automated test found that calls `cancel_deal` / `record_dispatch` / `apply_revision` as Fresko Salesperson vs Accounts and expects denial.
- **No** `has_permission` unit tests.

## ASSUMPTIONS

- DocType permissions are imported via migrate/fixtures as written in JSON.
- Users are not also given broad ERPNext roles that expand effective access beyond this matrix.

## UNKNOWN

- Effective permission when a user has both Fresko Salesperson and Fresko Approver.
- Whether Accounts can invoke whitelist methods that mutate Deals despite read-only DocType perm (Frappe whitelist typically bypasses DocType write if method uses `ignore_permissions` — **likely yes**, treat as gap until tested).

## RECOMMENDATIONS

1. Add explicit `frappe.only_for` / role checks mirroring this matrix on every whitelist method (**MUST FIX NOW** for cancel/dispatch/revision/apply_rate_rules).
2. Implement `has_permission` for Deal (owner/salesperson scoping) and container read for Salesperson.
3. Add permission regression tests that set_user to each Fresko role.
