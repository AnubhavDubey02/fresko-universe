# SECURITY_ARCHITECTURE — Fresko Universe

**Status:** living document · owned by Fresko Security  
**Scope:** Phase 0/1 scaffold on Frappe/ERPNext custom app `fresko_universe` (as of baseline).

## Separation of concerns (RECORDED FACTS)

- System of record: ERPNext/Frappe (pinned — see `docs/VERSIONS.md`).
- Fresko domain DocTypes live in custom app `fresko_universe` (not patched into upstream trees).
- Phase 1: Fresko Deal is operational commercial record; **no** Sales Order on approve (D1).
- Deterministic server rules control ATS, rate floors, approvals, immutability; AI may propose/extract later but must not silently establish financial truth (master brief + Dependency / AI rules).

## Trust boundaries (ASSUMPTIONS / to verify)

| Boundary | Notes |
|---|---|
| Desk / whitelisted Python methods | Primary mutation surface today |
| Future WhatsApp / OCR / LLM ingestion | Untrusted input; Phase 2+ |
| GitHub Actions / secrets | CI for Gate 2 bench |
| ERPNext roles + Fresko roles | Must enforce server-side |

## UNKNOWN

- Production auth IdP / SSO plan  
- Network / hosting topology  
- Whether any API is exposed beyond Frappe Desk  

Fill only with evidence from code, configs, and tests.
