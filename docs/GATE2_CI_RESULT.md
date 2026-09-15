# Gate 2 CI Result

**Date:** 2026-09-15  
**Branch:** `phase1-doctype-scaffold`  
**Tip SHA:** `3d9ac65a3aed0b64b9d02608b2fec392b40b8273` (`3d9ac65`)  
**Tip message:** `fix(D6): accept_counter opens BUYER_UNRESOLVED before Approved save`  
**App lineage under tip:** `3d9ac65` (D6 accept_counter BUYER_UNRESOLVED) → `703fc5a` (evidence pack docs) → `73273cd` (Gate2 docs) → `d785b63` (FSEC test hygiene)  
**Run (push):** [34957061073](https://github.com/AnubhavDubey02/fresko-universe/actions/runs/34957061073)  
**PR twin:** [34957065131](https://github.com/AnubhavDubey02/fresko-universe/actions/runs/34957065131) — same conclusion  
**Overall conclusion:** **success** (Smoke + Bench green)

## Pins (confirmed in Bench logs)

| App | Tag | SHA |
|-----|-----|-----|
| Frappe | v15.120.1 | `9f8ae9cd25b6735be345da6cc12e9f5a96050c68` |
| ERPNext | v15.121.2 | `df8b7f9648c2ec4da12db8c4022edc8dd1018c6b` |

Smoke pin assert also printed: `pins OK v15.120.1 v15.121.2`.

## Job results (tip `3d9ac65`)

| Job | Conclusion |
|-----|------------|
| Smoke unit (Gate 1 / D4 / constants) | **success** — `Ran 58 tests in 0.037s` / OK |
| Bench install + migrate + run-tests (pinned v15) | **success** — `Ran 61 tests in 4.122s` / OK / `==> CI bench OK` |

**58 smoke passed**, **61 bench passed**, **0 failures**, **0 errors**.

## Bench stage evidence (`==>` markers) — tip run

All infrastructure stages **passed**:

1. Pins Frappe/ERPNext — OK  
2. bench init → pin checkout → reinstall — OK  
3. new-site / install-app erpnext — OK  
4. Vendor + pip install + install-app fresko_universe — OK  
5. migrate — OK  
6. ERPNext `before_tests` — OK  
7. `run-tests --app fresko_universe` — OK (`Ran 61 tests in 4.122s`)  
8. `==> CI bench OK`

## Count delta vs prior green `d785b63`

| Suite | `d785b63` | `3d9ac65` | Delta |
|-------|-----------|-----------|-------|
| Smoke | 56 | 58 | +2 (D6 accept_counter BUYER_UNRESOLVED smoke) |
| Bench | 59 | 61 | +2 (D6 accept_counter bench coverage) |

Gate 1 fingerprint / D4 / D10 were **not** weakened.

## Success criteria mapping

- (a) Phase1 CI green with migrate+tests evidence on **current tip** — **met** (`3d9ac65`, Smoke 58 + Bench 61).  
- (b) No merge / no Phase 2 — **honored**.

**Do not merge the PR. Do not start Phase 2.**
