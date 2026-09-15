# DEPENDENCY POLICY — Dependency Sovereignty / Free-Forever

**Status:** LOCKED (Anubhav, 2026-09-15)  
**Owner:** Chief of Staff / Architecture  
**Applies to:** every library, framework, service SDK, CLI, container base image, and SaaS API that Fresko Universe relies on at build or runtime.

## Intent

Fresko Universe should preferentially reuse mature open-source code rather than recreate solved infrastructure. Critical functionality must remain maintainable by Fresko **without dependence on future upstream pricing**, license flips, or forced upgrades.

ERPNext/Frappe remain the system of record. Fresko business logic lives in the `fresko_universe` custom app (adapters/extensions), not inside upstream forks, unless Anubhav explicitly approves an unavoidable exception.

## Rules (mandatory)

1. **Prefer OSI-approved permissive licenses:** MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause, or ISC.
2. **GPL / AGPL / other copyleft** may be used only after documenting obligations in `THIRD_PARTY.md` (distribution, source offer, license notices, combination with proprietary code). Platform exception: Frappe + ERPNext (GPL-3.0) are approved strategic dependencies — see `THIRD_PARTY.md`.
3. **Do not** make a critical Fresko subsystem depend on source-available, fair-code, open-core, or commercial “community edition” functionality **without explicit Anubhav approval**.
4. **Record** every dependency in `docs/THIRD_PARTY.md`: repository URL, license, exact version/commit (or tag + SHA), and purpose.
5. **Pin** exact versions and SHAs (see also `docs/VERSIONS.md` and `.github/frappe-versions.json`). No floating `latest` / unpinned branch tips in production or CI.
6. **Strategic dependencies** (platform, auth, messaging, payments, storage that Fresko cannot quickly replace): maintain a Fresko-controlled fork **or** an immutable source archive (tarball/vendor commit) of the last approved version.
7. **Preserve** all required copyright, `LICENSE`, and `NOTICE` files for every dependency we redistribute or ship.
8. **Never** put Fresko business logic directly inside an upstream fork unless unavoidable. Prefer adapters, hooks, custom DocTypes, and the `fresko_universe` app.
9. **Provider integrations** (WhatsApp, OCR, LLM, payments, SMS, email) must sit behind **Fresko-owned interfaces**. Swapping a provider must not rewrite domain logic.
10. **Upstream updates are optional.** Fresko must be able to keep running the last approved pinned version indefinitely.
11. **Before writing a major subsystem from scratch**, search GitHub (and similar) for mature reusable implementations and perform license, security, and maintenance review.
12. **Before adopting a dependency**, compare maintenance cost of depending on it vs approximately how much engineering work it saves.

## Process — do not add dependencies automatically

Agents and engineers **must not** add a new runtime or strategic dependency without a written proposal and Anubhav (or delegated) approval.

### Proposal template (required)

| Field | Content |
|---|---|
| **Function** | What capability Fresko needs |
| **Candidate** | Project name + repository URL |
| **License** | SPDX id + link to LICENSE at pinned commit |
| **Maturity** | Stars/forks not enough — release cadence, bus factor, security history, last commit, who maintains it |
| **Code saved** | Rough engineering estimate avoided (person-days / complexity) |
| **Risks** | License flip, pricing, abandonware, supply-chain, copyleft obligations, SaaS kill-switch |
| **Fork strategy** | Fresko fork URL or immutable archive plan; how we stay on last approved version |
| **Recommendation** | Adopt / defer / build in-house / wrap behind Fresko interface |

After approval: pin version/SHA, add/update `THIRD_PARTY.md`, preserve LICENSE/NOTICE, and wire CI to the pin.

## Non-goals

- This policy does **not** ban Frappe/ERPNext (already chosen SoR; GPL obligations documented).
- This policy does **not** require inventing infrastructure Fresko can safely reuse under the rules above.
- Build-only / CI-only tools still need listing when they affect reproducibility or ship into artifacts; prefer permissive licenses there too.

## Related docs

- `docs/THIRD_PARTY.md` — inventory of approved / in-use third-party software  
- `docs/VERSIONS.md` — pinned Frappe / ERPNext SHAs for Gate 2  
- `docs/DECISIONS.md` — locked product and architecture decisions  
