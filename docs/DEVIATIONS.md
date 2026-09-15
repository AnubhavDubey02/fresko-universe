# DEVIATIONS — Phase 0+1 scaffold vs blueprint

No architecture blockers. Incremental deviations:

| ID | Item | Blueprint | Implemented | Why |
|---|---|---|---|---|
| DV1 | Rate middle tier child name | “Container+Product+Count” band | `Fresko Container Rate Band` renamed conceptually to **`Fresko Container Rate Rule`** child (`rate_rules` table); product implicit = container.item | Matches D5 grain without buyer floor; Product is container-level in V1 |
| DV2 | Lot floor field names | `rate_floor` / `rate_ceiling` on lot | `rate_floor_override` / `rate_ceiling_override` | Clearer that lot wins only when set |
| DV3 | Approval / Revision autoname | `APR-.YYYY.-.` / `REV-.YYYY.-.` | `hash` autoname | Append-only companions; avoid series contention in tests |
| DV4 | Oversell roles | Owner/Admin only (D10) | `{System Manager}` only — **Fresko Approver cannot oversell** | Locked D10; Approver alone insufficient; Exception + reason + Approval still required on override path |
| DV5 | ATS + Disputed | Not explicit | `Disputed` included in ATS-reducing set | Soft reservation should not free stock while disputed |
| DV6 | Partial dispatch qty | Status enum ready; child lines Phase 3 | `dispatched_qty` on Deal for ATS remaining math; Cancelled keeps `dispatched_qty` reserved | Blueprint §F / D2 provisional; QA cancel-after-partial |
| DV7 | Drive originals | — | Sample xlsx fixtures only in-repo; Drive IDs in SOURCES.md | Keep git light; WA zip Phase 2 |
| DV8 | Empty rate band | Fail-closed missing policy | **CLOSED Gate 1:** `policy_resolved` + `RATE_POLICY_MISSING` → Approval Required; no auto-approve when floor & ceiling None (F-M7) | Anubhav merge gate |
| DV9 | `frappe.db.set_value` bypass | Document.validate always | **Residual (non-blocking platform risk):** `db.set_value` skips Document.validate / commercial locks. Mitigate via whitelist APIs + audit; do not use in production paths or as supported test setup (F-I2) | Platform limitation |

If any of the above becomes unacceptable, escalate via `BLOCKER.md` (none filed for this PR).
