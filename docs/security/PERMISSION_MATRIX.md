# PERMISSION_MATRIX — Roles × DocTypes / sensitive actions

**Tip:** re-verify `fdbd9bd` on `phase1-doctype-scaffold` (FSEC-001/002/003 MITIGATED).  
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
| `apply_rate_rules` | Own deal | Yes | **Denied** | Yes | `assert_can_apply_rate_rules` then `ignore_permissions` | VERIFIED_IN_CODE |
| `approvals.decide` | Denied | Allowed | Denied (unless SM) | Allowed | `get_roles` check | VERIFIED_IN_CODE |
| Oversell override (D10) | Denied | Denied | Denied | Allowed | `OVERSELL_OVERRIDE_ROLES` | VERIFIED_IN_CODE |
| `accept_counter` | Only if owner or `salesperson_user` | Denied (even Approver) | Denied | Denied unless owner/salesperson | Explicit user ACL | VERIFIED_IN_CODE |
| `cancel_deal` | Own deal | Yes | **Denied** | Yes | `assert_can_cancel_deal` | VERIFIED_IN_CODE |
| `record_dispatch` | **Denied** | Yes | **Denied** | Yes | Approver/SM only | VERIFIED_IN_CODE |
| `request_revision` | Own deal | Yes | **Denied** | Yes | `assert_can_request_revision` | VERIFIED_IN_CODE |
| `apply_revision` | **Denied** | Yes | **Denied** | Yes | Approver/SM + Approval bound to deal + APPROVE/OVERSELL | VERIFIED_IN_CODE |
| Desk edit `approved_rate` | Blocked | Blocked | Blocked | Blocked without flag | validate + read_only | VERIFIED_IN_CODE |
| Desk edit `dispatched_qty` | Blocked | Blocked | Blocked | Blocked without flag | validate | VERIFIED_IN_CODE |
| Delete Approval | No | No | No | Yes (on_trash gate) | `fresko_approval.py` | VERIFIED_IN_CODE |
| Edit Approval after insert | No | No | No | No | append-only validate | VERIFIED_IN_CODE |
| `permission_query` row filters | Own/assigned | All | All | All | `deal_permission_query` / Evidence query | VERIFIED_IN_CODE |
| Whitelist validates role (controls claim) | — | — | — | — | `apply_revision` + other mutators gated in `permissions.py` | VERIFIED_IN_CODE |

## TEST RESULTS

- Pre-existing: `test_accept_counter_acl_owner_salesperson_only`, `test_system_manager_cannot_accept`, `test_approver_cannot_accept` (smoke); D10 oversell tests.
- **Added (tip `fdbd9bd`):** offline `TestFSEC001WhitelistACL`, `TestFSEC002ApplyRevisionBind`, `TestFSEC003DealPermissionHooks` in `tests/test_smoke_unit.py` — **18 tests OK** on re-verify (no bench).
- Bench module `fresko_universe.tests.test_fsec_permissions` asserts Accounts deny cancel/apply_rate, Salesperson ownership cancel, dispatch deny, Approval bind/mismatch/REJECT, two-sales permission_query — **not run** this re-verify (no site).

## ASSUMPTIONS

- DocType permissions are imported via migrate/fixtures as written in JSON.
- Users are not also given broad ERPNext roles that expand effective access beyond this matrix.

## UNKNOWN

- Effective permission when a user has both Fresko Salesperson and Fresko Approver (hook order: Approver wins over Accounts-only; Salesperson+Accounts hits Salesperson branch).
- Live Desk/UI confirmation that Role Permission Manager + hooks combine as expected on a migrated site (static + offline smoke only this pass).

## RECOMMENDATIONS

1. ~~MUST FIX NOW whitelist ACL~~ — **MITIGATED** at `fdbd9bd` (`permissions.py` gates). Keep regression tests green.
2. ~~`has_permission` / `permission_query` for Deal (+ Evidence)~~ — **MITIGATED** via `hooks.py`. Residual: tighten Deal JSON write or add Container/Revision hooks (defense-in-depth).
3. Run bench `test_fsec_permissions` on a site before claiming Gate green; keep offline smoke in CI.
4. Still open elsewhere: Evidence hash/bytes (FSEC-004), Evidence.message_id unique (FSEC-005), CI scanners (FSEC-006), compose binds (FSEC-007).
