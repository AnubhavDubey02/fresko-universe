# Fresko Security Ledger

**Owner role:** Fresko Security & Red Team Engineer (independent of implementers).  
**Repo tip assessed:** `phase1-doctype-scaffold` @ `18c5042` (2026-09-15).  
**Remote:** https://github.com/AnubhavDubey02/fresko-universe.git  
**Policy companions:** `docs/DEPENDENCY_POLICY.md`, `docs/THIRD_PARTY.md`, `docs/VERSIONS.md`, `docs/DECISIONS.md`, `docs/controls.md`.

A feature is **not** secure because the implementing agent says it is. Security is ongoing and adversarial. This ledger records evidence from **current code + docs**, not design intent alone.

## Documents

| File | Purpose |
|---|---|
| [SECURITY_ARCHITECTURE.md](SECURITY_ARCHITECTURE.md) | Authn/z, evidence, approvals, trust boundaries as implemented |
| [THREAT_MODEL.md](THREAT_MODEL.md) | Assets, adversaries, abuse cases for Phase 1 Container+Deal |
| [PERMISSION_MATRIX.md](PERMISSION_MATRIX.md) | Role × DocType/action; VERIFIED_IN_CODE vs DOC_ONLY vs UNKNOWN |
| [SECURITY_FINDINGS.md](SECURITY_FINDINGS.md) | Living findings (severity + OPEN status + evidence paths) |
| [SECURITY_TESTING.md](SECURITY_TESTING.md) | Existing tests vs needed security regression coverage |
| [BASELINE_ASSESSMENT.md](BASELINE_ASSESSMENT.md) | Prioritized backlog with concrete repo evidence |
| [ROLE_SECURITY_RED_TEAM.md](ROLE_SECURITY_RED_TEAM.md) | Locked Security & Red Team role charter |

## How Security works with other agents

| Agent | Security interaction |
|---|---|
| **Implementers (Codex / app agents)** | Ship DocTypes + whitelist methods; Security reviews diffs against this ledger and rejects “trust the UI” claims |
| **Controls / Accounting** | Owns financial-control intent in `docs/controls.md`; Security flags when code diverges (finding) |
| **QA / Adversarial** | Owns attack reports (`docs/QA_CONTAINER_DEAL_ATTACK_REPORT.md`, `docs/QA_REVIEW_*`); Security promotes residual breaks into `SECURITY_FINDINGS.md` |
| **CI / Gate agents** | Wire regression tests; Security requires SAST/secret/dep/permission signals — currently largely **missing** (see findings) |
| **Anubhav (human)** | Approves CRITICAL/HIGH deploy overrides, dependency proposals, D10 System Manager oversell |

## Evidence rules

Every significant claim must cite **repository evidence** (path:line, test name, or CI run id). Separate:

- **RECORDED FACTS** — observed in code/config/docs on tip
- **TEST RESULTS** — what automated tests actually assert (or CI recorded)
- **ASSUMPTIONS** — operating assumptions, not proven
- **UNKNOWN** — not verified this baseline
- **RECOMMENDATIONS** — MUST FIX NOW / BEFORE PRODUCTION / LATER HARDENING

Do **not** declare Fresko “secure.” Scanner hit ≠ compromise; absence of scanner ≠ secure.
