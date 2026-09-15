# Gate 2 CI Result

**Date:** 2026-09-15  
**Branch:** `phase1-doctype-scaffold`  
**Tip SHA:** `d785b632803948d9b1b6c6a54423db143f50c0ca` (`d785b63`)  
**Tip message:** `test(fsec): unique make_deal buyer_alias to avoid fingerprint collisions`  
**App lineage under tip:** `d785b63` (FSEC test hygiene) → `f7db7c3` (re-verify docs) → `fdbd9bd` (FSEC ACL) on Gate2 rate fixes `00e1273` / `b5f8dc9` / `dafed00`  
**Run (push):** [34954607466](https://github.com/AnubhavDubey02/fresko-universe/actions/runs/34954607466)  
**PR twin:** [34954609241](https://github.com/AnubhavDubey02/fresko-universe/actions/runs/34954609241) — same conclusion  
**Overall conclusion:** **success** (Smoke + Bench green)

## Pins (confirmed in Bench logs)

| App | Tag | SHA |
|-----|-----|-----|
| Frappe | v15.120.1 | `9f8ae9cd25b6735be345da6cc12e9f5a96050c68` |
| ERPNext | v15.121.2 | `df8b7f9648c2ec4da12db8c4022edc8dd1018c6b` |

Smoke pin assert also printed: `pins OK v15.120.1 v15.121.2`.

## Job results (tip `d785b63`)

| Job | Conclusion |
|-----|------------|
| Smoke unit (Gate 1 / D4 / constants) | **success** — `Ran 56 tests in 0.065s` / OK |
| Bench install + migrate + run-tests (pinned v15) | **success** — `Ran 59 tests in 3.843s` / OK / `==> CI bench OK` |

**56 smoke passed**, **59 bench passed**, **0 failures**, **0 errors**.

## Bench stage evidence (`==>` markers) — tip run

All infrastructure stages **passed**:

1. Pins Frappe/ERPNext — OK  
2. bench init → pin checkout → reinstall — OK  
3. new-site / install-app erpnext — OK  
4. Vendor + pip install + install-app fresko_universe — OK  
5. migrate — OK  
6. ERPNext `before_tests` — OK  
7. `run-tests --app fresko_universe` — OK (`Ran 59 tests in 3.843s`)  
8. `==> CI bench OK`

## Prior red tip (resolved by this watch)

| Item | Value |
|------|-------|
| SHA | `f7db7c35ad784f750a073399f17a7a964a1fb332` (`f7db7c3`) |
| Bench | `FAILED (errors=2)` — FSEC `make_deal` fingerprint collisions |
| Fix | `d785b63` unique `buyer_alias` per deal in FSEC fixtures (test hygiene only) |

Gate 1 fingerprint / D4 / D10 were **not** weakened.

## Success criteria mapping

- (a) Phase1 CI green with migrate+tests evidence on **current tip** — **met** (`d785b63`, Smoke 56 + Bench 59).  
- (b) No merge / no Phase 2 — **honored**.

**Do not merge the PR. Do not start Phase 2.**
