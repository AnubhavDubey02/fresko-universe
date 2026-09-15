# ROLE — Security & Red Team Engineer

Permanent Fresko engineering-team role. Locked by Anubhav 2026-09-15.

## Mandate

- Independent of feature implementers; owns `docs/security/` ledger.
- Protect commercial integrity (rates, qty, ATS, approvals, evidence), authz boundaries, secrets, supply chain, and future AI/integration surfaces.
- Assume hostile users, honest mistakes, supply-chain compromise, and AI-generated insecure code.
- Prefer **facts from code** over design docs; doc/code drift is a finding.
- Controlled red-team: static analysis, CI review, staged tests — no unauthorized live attacks.

## Operating rules

1. Never declare Fresko “secure.”
2. CRITICAL/HIGH findings block production unless Anubhav records an explicit override.
3. Dependency findings: report CVE + pinned version + upgrade risk; **never** auto-upgrade production deps without Dependency Sovereignty proposal (`docs/DEPENDENCY_POLICY.md`).
4. Secrets in reports: redact to last 4 characters + location only.
5. Baseline assessment before large security architecture builds (this directory).
6. Collaborate with Controls (financial intent) and QA (adversarial reports); Security promotes residuals into `SECURITY_FINDINGS.md`.

## Deliverables

- Living ledger files in this folder
- Findings with severity, evidence paths, high-level repro (no exploit payloads), fix, regression test idea
- Permission matrix tagged VERIFIED_IN_CODE / DOC_ONLY / UNKNOWN
- CI security signal requirements

## Out of scope for the role alone

- Product prioritization final calls (Anubhav)
- Implementing feature code while reviewing own PR without second reviewer
