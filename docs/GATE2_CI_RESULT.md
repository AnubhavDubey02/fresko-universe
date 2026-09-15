# Gate 2 CI Result

**Date:** 2026-09-15  
**Branch:** `phase1-doctype-scaffold`  
**Tip SHA:** `6ee6cb9f6b4287fb871cd8cb23c544f77c8fa691` (`6ee6cb9`)  
**Tip message:** `fix(phase1): ChatGPT blockers — commercial lock, revision-bound Approval, Countered rate RC`  
**App lineage under tip:** `6ee6cb9` (ChatGPT blockers: commercial lock / revision-bound Approval / Countered rate RC) → `583e48b` (security review docs) → `2f43aa2` (Gate2 docs on 3d9ac65) → `3d9ac65` (D6 accept_counter BUYER_UNRESOLVED)  
**Run (push):** [34960445631](https://github.com/AnubhavDubey02/fresko-universe/actions/runs/34960445631)  
**PR twin:** [34960454085](https://github.com/AnubhavDubey02/fresko-universe/actions/runs/34960454085) — same conclusion  
**Overall conclusion:** **success** (Smoke + Bench green)

## Pins (confirmed in Bench logs)

| App | Tag | SHA |
|-----|-----|-----|
| Frappe | v15.120.1 | `9f8ae9cd25b6735be345da6cc12e9f5a96050c68` |
| ERPNext | v15.121.2 | `df8b7f9648c2ec4da12db8c4022edc8dd1018c6b` |

Smoke pin assert also printed: `pins OK v15.120.1 v15.121.2`.

## Job results (tip `6ee6cb9`)

| Job | Conclusion |
|-----|------------|
| Smoke unit (Gate 1 / D4 / constants) | **success** — `Ran 75 tests in 0.082s` / OK |
| Bench install + migrate + run-tests (pinned v15) | **success** — `Ran 75 tests in 4.948s` / OK / `==> CI bench OK` |

**75 smoke passed**, **75 bench passed**, **0 failures**, **0 errors**.

## Bench stage evidence (`==>` markers) — tip run

All infrastructure stages **passed**:

1. Pins Frappe/ERPNext — OK  
2. bench init → pin checkout → reinstall — OK  
3. new-site / install-app erpnext — OK  
4. Vendor + pip install + install-app fresko_universe — OK  
5. migrate — OK  
6. ERPNext `before_tests` — OK  
7. `run-tests --app fresko_universe` — OK (`Ran 75 tests in 4.948s`)  
8. `==> CI bench OK`

## Count delta vs prior green `3d9ac65`

| Suite | `3d9ac65` | `6ee6cb9` | Delta |
|-------|----------|----------|-------|
| Smoke | 58 | 75 | +17 (ChatGPT blocker coverage: commercial lock, revision-bind Approval, Countered rate RC, FSEC bind/ACL smokes) |
| Bench | 61 | 75 | +14 (same blocker suite on bench) |

Gate 1 fingerprint / D4 / D10 were **not** weakened.

## Success criteria mapping

- (a) Phase1 CI green with migrate+tests evidence on **current tip** — **met** (`6ee6cb9`, Smoke 75 + Bench 75).  
- (b) No merge / no Phase 2 — **honored**.

**Do not merge the PR. Do not start Phase 2.**
