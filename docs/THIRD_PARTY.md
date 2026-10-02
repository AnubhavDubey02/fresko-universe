# THIRD_PARTY — approved and in-use dependencies

**Policy:** `docs/DEPENDENCY_POLICY.md` (Dependency Sovereignty / Free-Forever — LOCKED 2026-09-15).  
**Rule:** every runtime or strategic dependency must appear here with URL, license, exact pin, and purpose. Do not add new entries without a proposal (see policy).

Pins for Frappe/ERPNext are authoritative in `docs/VERSIONS.md` and `.github/frappe-versions.json`.

---

## Strategic platform (approved)

### Frappe Framework

| Field | Value |
|---|---|
| **Repository** | https://github.com/frappe/frappe |
| **License** | GPL-3.0-or-later (copyleft — obligations documented below) |
| **Pin** | Tag `v15.120.1` · SHA `9f8ae9cd25b6735be345da6cc12e9f5a96050c68` |
| **Purpose** | Application framework / metadata / permissions / ORM for Fresko DocTypes |
| **Fork / archive** | Strategic: stay on last approved pin via CI; Fresko-controlled fork or immutable archive required before any forced upgrade path or license-threatening upstream change |
| **Integration style** | Custom app `fresko_universe` only — no Fresko domain logic inside the Frappe tree |

**GPL obligations (summary):** distributing a modified Frappe (or a combined work that is a derivative under GPL) requires providing corresponding source under GPL-3.0 terms and preserving copyright/license notices. Fresko ships customization as a **separate custom app** where possible. Legal review remains Anubhav’s call for any redistribution model beyond internal/self-hosted use.

### ERPNext

| Field | Value |
|---|---|
| **Repository** | https://github.com/frappe/erpnext |
| **License** | GPL-3.0-or-later (copyleft — same obligation class as Frappe) |
| **Pin** | Tag `v15.121.2` · SHA `df8b7f9648c2ec4da12db8c4022edc8dd1018c6b` |
| **Purpose** | System of record for Customer, Item, Warehouse, Batch, Company, and (later) SO/DN/stock ledgers |
| **Fork / archive** | Same strategic treatment as Frappe |
| **Integration style** | Link fields + Phase 3 boundaries; Fresko Deal/Container remain Fresko DocTypes (D1: no SO on approve in Phase 1) |

---

## Build / packaging (app)

### flit_core (build-system)

| Field | Value |
|---|---|
| **Repository** | https://github.com/pypa/flit |
| **License** | BSD-3-Clause (permissive) |
| **Pin** | Declared in `fresko_universe/pyproject.toml` as `flit_core >=3.4,<4` for build-backend — **tighten to an exact pin before production release packaging** |
| **Purpose** | PEP 517 build backend for the `fresko_universe` Python package |
| **Note** | Build-only; not imported by Fresko business logic |

---

## Application runtime Python dependencies

`fresko_universe` `pyproject.toml` currently declares **`dependencies = []`**.

No additional third-party Python packages are approved for Phase 0/1 beyond what Frappe/ERPNext already pull in as transitive framework dependencies. Those transitive packages are inherited from the **pinned** Frappe/ERPNext SHAs above; do not add direct Fresko dependencies without a proposal.

---

## Explicitly out of scope until approved

Do **not** adopt without a filled proposal + Anubhav approval, including but not limited to:

- WhatsApp / Meta Business SDKs or BSPs  
- OCR / document AI vendors  
- LLM provider SDKs (must sit behind a Fresko-owned interface)  
- Payment gateways  
- Source-available / fair-code / open-core products for critical paths  

---

## Change log

| Date | Change |
|---|---|
| 2026-09-15 | Initial inventory: Frappe + ERPNext pins; flit_core build-system; empty app runtime deps |
