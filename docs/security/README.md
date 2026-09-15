# Fresko Security Ledger

**Owner role:** Fresko Security & Red Team Engineer (independent of implementers).  
**Policy companions:** `docs/DEPENDENCY_POLICY.md`, `docs/THIRD_PARTY.md`, `docs/DECISIONS.md`.

A feature is **not** secure because the implementing agent says it is. Security is ongoing and adversarial.

## Documents

| File | Purpose |
|---|---|
| [SECURITY_ARCHITECTURE.md](SECURITY_ARCHITECTURE.md) | How authn/z, evidence, approvals, and trust boundaries actually work in Fresko |
| [THREAT_MODEL.md](THREAT_MODEL.md) | Assets, adversaries, trust boundaries, abuse cases |
| [PERMISSION_MATRIX.md](PERMISSION_MATRIX.md) | Role × sensitive action matrix + backend enforcement evidence |
| [SECURITY_FINDINGS.md](SECURITY_FINDINGS.md) | Living findings log (severity + status) |
| [SECURITY_TESTING.md](SECURITY_TESTING.md) | How we attack/test; CI signals vs proof |
| [BASELINE_ASSESSMENT.md](BASELINE_ASSESSMENT.md) | Initial repo assessment + prioritized backlog |

Every significant claim must cite **repository evidence** (path, test, or CI run). Separate:

- RECORDED FACTS  
- TEST RESULTS  
- ASSUMPTIONS  
- UNKNOWN AREAS  
- RECOMMENDATIONS (MUST FIX NOW / BEFORE PRODUCTION / LATER HARDENING)

Do **not** declare Fresko “secure.”
