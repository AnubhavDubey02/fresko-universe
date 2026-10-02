# THREAT_MODEL — Fresko Phase 1 (Container + Deal)

**Tip:** `18c5042`. Method: STRIDE-style abuse cases grounded in current code + `docs/QA_CONTAINER_DEAL_ATTACK_REPORT.md`.

## RECORDED FACTS — Assets

| Asset | Why it matters | Where it lives |
|---|---|---|
| Approved commercial qty / rate | Partner settlement / oversell risk | `Fresko Deal` + ATS math |
| Rate floor/ceiling policy | Margin floor | Container defaults, lot overrides, rate_rules |
| Approval / Revision trail | Non-repudiation of rate/qty changes | `Fresko Approval`, `Fresko Revision` |
| Evidence originals | Dispute / audit | `Fresko Evidence` Attach + hash fields |
| Buyer identity | Receivable attribution | `buyer_alias` (immutable) + `customer` |
| Container inward / lot membership | Physical vs commercial truth | `Fresko Container` + child lots |
| Role assignments | Who can approve / oversell | Role fixtures + Frappe User roles |
| Bench / DB credentials | Infra compromise | Compose + CI defaults |

## Adversaries / actors

1. **Malicious or mistaken Salesperson** (authenticated Desk).
2. **Malicious Approver** (can decide rates; must not D10-oversell alone — coded).
3. **Compromised System Manager** (D10 oversell + delete Approvals).
4. **Insider with any Desk login** invoking whitelist RPC (Frappe allows authenticated users to call `@frappe.whitelist` unless method checks roles).
5. **Supply-chain** — compromised CI action or unpinned tool (`actions/checkout@v4` major-pin only).
6. **Future:** WhatsApp webhook forger / LLM prompt injector (Phase 2 — not in code).

## Abuse cases (mapped)

| ID | Abuse | Mitigations in code today | Residual |
|---|---|---|---|
| A1 | Double-deal same WhatsApp / fingerprint | Deal unique `source_message_id` + `duplicate_fingerprint`; Evidence+Exception on dup FP | Evidence.`message_id` not unique; WhatsApp ingest not built |
| A2 | Concurrent oversell same lot | `FOR UPDATE` + ATS on approve paths; tests exist | Race coverage depends on bench suite green; Proposed does not reserve (by design D3) |
| A3 | Desk overwrite `approved_rate` | validate + read_only + flags | `frappe.db.set_value` bypass called out in comments as unsupported |
| A4 | Steal `accept_counter` | D4 ACL + `salesperson_user` in commercial lock | Owner account compromise still succeeds |
| A5 | Approver self-oversell | D10 `OVERSELL_OVERRIDE_ROLES = {System Manager}` | SM is powerful; no dual-control |
| A6 | Apply material revision without real approval | Requires Approval doc **exists** | Does not verify Approval.deal / decision / status linkage or caller role |
| A7 | Cancel / dispatch another user’s deal | Status/qty rules exist | **No role/ownership check** on `cancel_deal` / `record_dispatch` |
| A8 | Forge evidence integrity | Immutable fields after set | Hash is of path string, not bytes |
| A9 | Close container while material exceptions open | `_validate_close_gate` | Depends on exception types listed; severity taxonomy partial |
| A10 | CI / compose credential reuse in prod | Docs say CI-only | Easy footgun if compose reused |

## Trust boundaries diagram (logical)

```
[Desk User] --session--> [Frappe] --whitelist/DocType--> [fresko_universe controllers]
                              |                              |
                              v                              v
                         [MariaDB] <------------------ [ATS FOR UPDATE]
                              ^
[CI / Compose] --root/root--> |
```

## TEST RESULTS

- Threats A3/A4/A5 partially covered by smoke/acceptance tests (desk rate lock, D4 ACL, D10).
- Threats A6/A7 (revision Approval bind; cancel/dispatch authz) **lack** negative role tests.
- Concurrent ATS (A2) has acceptance tests; Gate 2 tip health UNKNOWN.
- No live red-team execution this baseline.

## ASSUMPTIONS

- Attackers are authenticated unless Frappe misconfigured for Guest.
- Physical warehouse systems are out of band (dispatch stub is commercial only).

## UNKNOWN

- Network exposure of future production bench.
- Whether Site Guest/API keys will be issued for integrations before Phase 2 controls land.

## RECOMMENDATIONS

Prioritize A6/A7 (authz on whitelist), A8 (real content hashing), A1 Evidence uniqueness before WhatsApp ingest, and remove public DB ports from any shared environment.
