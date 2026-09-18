# Gate 2 CI Result

## Exact `f907b8b` evidence — 2026-09-18

**Verified repository/PR:** `AnubhavDubey02/fresko-universe` PR #2, open and
unmerged at verification time.

**Exact checked-out SHA:** `f907b8b8af4e7b4d4b3240af43a237682508647d`
(`f907b8b`)

**Immutable app parent:** `25859fc8c9daea9eedc07f484c79c7ed59249efa`
(`25859fc`)

**Diff from app parent:** documentation only (`docs/GATE2_CI_RESULT.md` and
`docs/OPEN_QUESTIONS.md`).

Primary exact-SHA run:
[35329916947](https://github.com/AnubhavDubey02/fresko-universe/actions/runs/35329916947)
(`pull_request`, run 70). Push twin:
[35329913359](https://github.com/AnubhavDubey02/fresko-universe/actions/runs/35329913359)
(`push`, run 69). Both completed `success` with head SHA exactly `f907b8b`.

| Gate in primary run 35329916947 | Result | Test count | Failures | Errors | Test skips |
|---|---|---:|---:|---:|---:|
| Smoke unit (Gate 1 / D4 / constants) | success | 78 | 0 | 0 | 0 |
| Bench install + migrate + run-tests (pinned v15) | success | 81 | 0 | 0 | 0 |

The bench log ends `Ran 81 tests`, `OK`, and `==> CI bench OK`; the smoke log
ends `Ran 78 tests`, `OK`. Frappe `v15.120.1` and ERPNext `v15.121.2` pins were
asserted. The workflow's failure-only **Upload bench logs on failure** step was
skipped because the bench succeeded; that conditional workflow skip is not a
skipped test. No failure required investigation on `f907b8b`.

This exact-SHA evidence supersedes reliance on the earlier 75/75 result and
closes the evidence gap after the failed `bb59e18` bench. It does not authorize
merging PR #2 or starting Phase 2.

## Current-tip repair verification — 2026-09-18

**Tip SHA:** `25859fc8c9daea9eedc07f484c79c7ed59249efa` (`25859fc`)

**Tip message:** `fix(phase1): refresh dispatch ceiling under lock`

**Failed predecessor run:** [34998759732](https://github.com/AnubhavDubey02/fresko-universe/actions/runs/34998759732) on `bb59e180e528a29ad26039e7d6b7f333a8683db9`

**Repair runs:** [35329138786](https://github.com/AnubhavDubey02/fresko-universe/actions/runs/35329138786) (PR) and [35329134656](https://github.com/AnubhavDubey02/fresko-universe/actions/runs/35329134656) (push)

**Overall conclusion:** **success** on both exact-SHA runs; PR #2 remains open and unmerged.

The predecessor smoke job passed, but its pinned MariaDB bench failed
`test_concurrent_dispatches_cannot_exceed_lot_inward`: both 60-unit dispatches
committed against one 100-unit lot. The Container row lock existed, but normal
Deal and aggregate reads after the wait could retain a pre-lock snapshot under
MariaDB `REPEATABLE READ`.

The repair retains the stable Container lock, then reloads the Deal with
`for_update=True` and uses locking reads for lot inward and peer dispatched
quantities. The offline contract now asserts that those reads occur after the
shared lock.

| Gate | Result on `25859fc` |
|---|---|
| Local smoke | **78 passed** (`python3 -m unittest tests.test_smoke_unit -v`) |
| PR smoke | **success** |
| PR pinned bench | **81 passed**, 0 failures/errors; migrate + ERPNext bootstrap + `CI bench OK` |
| Push twin | **success** (smoke + pinned bench) |

This supersedes the earlier 75/75 result only for current-tip verification; the
older evidence below remains immutable evidence for `6ee6cb9`. No Phase 2 work
was started, and this repair does not authorize merging PR #2.

---

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
