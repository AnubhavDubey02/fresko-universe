# SECURITY_ARCHITECTURE — Fresko Universe (Phase 1 tip)

**Assessed tip:** `18c5042` on `phase1-doctype-scaffold`.  
**Scope:** `fresko_universe` custom app (Container + Deal), fixtures, Docker/CI, docs.

## RECORDED FACTS

### Trust boundaries

1. **Browser Desk / desk API** → Frappe session auth → `fresko_universe` DocTypes + `@frappe.whitelist()` methods. No `allow_guest=True` found on Fresko whitelist methods (`deals.py`, `approvals.py`, `container.py`, `fresko_container.py`).
2. **MariaDB** — commercial truth for Deals/Containers/Approvals/Evidence/Exceptions/Revisions. Docker Compose publishes `3306` with `MYSQL_ROOT_PASSWORD=root` (`docker-compose.yml`, `docker-compose.bench.yml`).
3. **Redis** — Frappe cache/queue; published `6379` in compose files (no auth configured in compose).
4. **ERPNext masters** — Customer/Item/Company/UOM linked from Fresko DocTypes; Phase 1 does not post Sales Order on approve (D1 / docs).
5. **CI runner** — GitHub Actions `Phase1 CI` (`.github/workflows/ci.yml`): smoke-unit offline + optional heavy bench job; DB password `root`, admin default in `scripts/ci_bench.sh`.

### Authentication

- Relies entirely on **Frappe session / Desk login**. No Fresko-specific auth module.
- Roles created at install/migrate: `Fresko Salesperson`, `Fresko Approver`, `Fresko Accounts` (`hooks.py` fixtures + `install.py` + `fixtures/role.json`).
- No SSO/OIDC/SAML configuration in this repo.

### Authorization model (as coded)

| Layer | What exists | Evidence |
|---|---|---|
| DocType Role Permission Manager JSON | Coarse CRUD per role on parent DocTypes | `fresko_*.json` `permissions` arrays |
| Server Document.validate | Status machine, commercial locks, dispatch lock, buyer gate | `fresko_deal.py`, `fresko_container.py` |
| Whitelist method ACL | **Only** `approvals.decide` checks Approver/SM; `accept_counter` checks owner/salesperson | `approvals.py:38-40`, `deals.py:111-119` |
| `has_permission` / `permission_query` | **Absent** in app Python | repo-wide search: none |
| `ignore_permissions=True` | Used on save/insert paths in whitelist helpers | `deals.py`, `approvals.py` |

### Whitelisted attack surface (authenticated)

| Method | File | Role gate in method body? |
|---|---|---|
| `fresko_universe.deals.apply_rate_rules` | `deals.py:14` | No |
| `fresko_universe.deals.accept_counter` | `deals.py:100` | Yes — owner or `salesperson_user` only (D4) |
| `fresko_universe.deals.cancel_deal` | `deals.py:135` | No |
| `fresko_universe.deals.record_dispatch` | `deals.py:158` | No |
| `fresko_universe.deals.set_dispatched_qty` | `deals.py:357` | No (shim) |
| `fresko_universe.deals.request_revision` | `deals.py:221` | No |
| `fresko_universe.deals.apply_revision` | `deals.py:283` | No role check; requires Approval **name exists** for material fields |
| `fresko_universe.approvals.decide` | `approvals.py:14` | Yes — Fresko Approver or System Manager; D10 SM-only oversell |
| `fresko_universe.container.snapshot` | `container.py:12` | No |
| `fresko_universe.fresko_core.doctype.fresko_container.fresko_container.container_snapshot` | `fresko_container.py:161` | No |

### Business-control architecture (server-enforced highlights)

- **ATS (D3):** `fresko_core/ats.py` — Proposed/Approval Required/Countered do not reduce ATS; Approved+ reduce; Cancelled keeps `dispatched_qty`. Optional `FOR UPDATE` on container row when `for_update=True`.
- **Rate policy (D5 / Gate 1):** `rate_rules.py` + `apply_rate_rules` — empty band → Approval Required + `RATE_POLICY_MISSING` exception; does **not** auto-approve.
- **Commercial lock:** `COMMERCIAL_LOCK_STATUSES` + `LOCKED_COMMERCIAL_FIELDS` in `constants.py`; Desk edit of `approved_rate` / locked fields blocked unless flags set by whitelist paths (`fresko_deal.py`).
- **Approvals append-only:** `FreskoApproval.validate` rejects edits; delete restricted to System Manager (`fresko_approval.py`).
- **Revisions:** Pending → Applied only via `apply_revision` + `allow_revision_apply` flag; historical fields frozen after Applied.
- **Evidence immutability:** Once set, `content_sha256` / `message_id` / `file` / `external_ref` cannot change (`fresko_evidence.py`). Hash on insert is **SHA-256 of file URL/path string**, not file bytes (`fresko_evidence.py:17-21`).
- **Idempotency (partial):** Deal `source_message_id` and `duplicate_fingerprint` marked `unique: 1` in DocType JSON; validated in `_validate_idempotency_keys`. Evidence `message_id` is **not** unique in JSON.

### Public JS / uploads

- Client JS stubs only (`fresko_deal.js`, `fresko_container.js`, `public/js/fresko_universe.js`) — no client-side security logic.
- Uploads: `Fresko Evidence.file` (Attach), `Fresko Container Source Document.attachment` (Attach). No Fresko-specific MIME/size/malware controls in app code.

### AI / LLM / WhatsApp / OCR

- **Not implemented** in `fresko_universe` Python/JS (no openai/anthropic/whatsapp/ocr imports). Phase 2 surfaces are documentation-only (`THIRD_PARTY.md` “out of scope until approved”).

### Secrets handling

- `.env.example` contains site name + public Frappe/ERPNext pin SHAs only (no live secrets).
- `.gitignore` ignores `.env`, `sites/`, `venv/`; does **not** ignore `*.pem`, `*.key`, `site_config.json`, credential filenames.
- Working-tree secret pattern scan: only CI default password assignments in `scripts/ci_bench.sh` (`DB_ROOT_PASSWORD` default `root`, `ADMIN_PASSWORD` default `admin`).
- Git history pattern scan for AWS keys / PEM / `ghp_` / `sk-`: **no hits**.

### Dependencies

- App `pyproject.toml`: `dependencies = []`; build `flit_core >=3.4,<4` (range, not exact pin).
- Platform pins: Frappe `v15.120.1` / SHA `9f8ae9cd…0c68`; ERPNext `v15.121.2` / SHA `df8b7f96…8c6b` (`.github/frappe-versions.json`, `docs/VERSIONS.md`).
- CVE status for platform pins: **UNKNOWN** this baseline (no successful advisory/pip-audit against installed Frappe tree on this box).

## TEST RESULTS

- Offline smoke (`tests/test_smoke_unit.py`): D4 ACL unit asserts, D10 role constant, Gate 1 band logic, commercial lock constants — designed to run without bench.
- Bench acceptance (`test_phase1_acceptance.py`, `test_fresko_deal.py`): ATS concurrency soft-route, desk edit rejects, revision+approval, oversell exception — require Frappe site.
- Last recorded Gate 2 run (`docs/GATE2_CI_RESULT.md`, tip `6a4db0e`): smoke **success**, bench **FAILED** (11 fail / 8 error). Later commits claim fixes (`dafed00`); **re-run status on tip `18c5042` not verified in this baseline**.

## ASSUMPTIONS

- Production will sit behind TLS and not expose MariaDB/Redis publicly (compose today does bind ports).
- Frappe CSRF / session cookie defaults remain enabled upstream.
- System Manager is a break-glass role, not day-to-day ops.

## UNKNOWN

- Whether Frappe File upload max size / allowed extensions are configured on target sites.
- Runtime permission resolution when users hold multiple Fresko roles + ERPNext roles.
- Whether unique indexes for Deal fingerprint/`source_message_id` successfully migrate on all MariaDB configs (JSON declares `unique: 1`; migration not re-proven here).
- Upstream CVEs for pinned Frappe/ERPNext transitive deps.

## RECOMMENDATIONS

See `BASELINE_ASSESSMENT.md` and `SECURITY_FINDINGS.md`. Highest leverage: enforce role checks on every whitelist method; bind Approval→Deal on `apply_revision`; add `permission_query`/`has_permission`; wire CI secret/SAST/dep scans.
