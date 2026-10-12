# Fresko staging execution report — 12 October 2026

**CONDITIONAL GO — private synthetic staging accepted within the tested scope.** The existing cloud site's data remains unclassified and has not been imported, migrated, restored or overwritten. No production release or real-data financial posting is approved by this report.

## A. Source and integration

Application branch: `codex/fresko-integrated-staging-20261017`.

Exact deployed application SHA: `27f859a4135f739513cc103d5fe93e9f8a3be796`.

[Draft integration PR 26](https://github.com/AnubhavDubey02/fresko-universe/pull/26). It remains unmerged. Other contributors' pull requests and branches were preserved.

| Commit | Change |
|---|---|
| `25d0b46351d3100acd5e2ad1d852a10619f18751` | Server-derived ownership for new parentless Evidence; private-file, parent-link and HTTP fences; additive migration proof. |
| `19e2814d437dee02310ee2260727283c55ecfc67` | Distinguish legacy permission policy from the fresh session-principal fence in regression tests. |
| `35a72b85bd5fcbe049f13841947a62d91f64aec2` | Resolve a verified Sale lot through its actual child link inside the authorized Container. |
| `27f859a4135f739513cc103d5fe93e9f8a3be796` | Nonzero reporting fixtures, native API/browser drivers and independent downloaded-CSV Decimal checks. |

The preserved Flash baseline was `584c12d118d06cdbcec06d1508b04718f3530a0d`. Gemini 3.8 Flash High prepared reporting/recovery work and the fresh source/environment and browser asset build. Codex owned the security implementation, reviewed drafts, corrected concrete failures, verified results and finished work when Flash exhausted its quota. No alternate Flash model or paid upgrade was used.

[Exact-candidate CI run 197](https://github.com/AnubhavDubey02/fresko-universe/actions/runs/38172131291): both jobs SUCCESS; **325 native tests in 139.319s**, **8 browser/recovery tests in 525.133s**, seeded/repeated migration proofs and offline/UI/schema guards passed. Earlier CI run 195 failed one legacy permission expectation; run 196 passed at `19e2814`. Those ancestors are historical evidence, not the certification for the final SHA.

The application archive SHA256 is `1055c401c36887d015faf66f1eae86ff4bee5539462bc1d8ff59f5b7633bd2ec`. Source and application import paths were independently checked on the VM. The separate operations branch `codex/fresko-staging-operations-20261012` records this report and exact nonsecret deployed control files; it does not change the deployed application SHA.

## B. Parentless Evidence

The reproduced defect required a Deal or Container before source intake could determine ownership. Allowing arbitrary caller-supplied Company would create a cross-company access path.

New manual Evidence instead receives an immutable server-derived `evidence_company` from the currently enabled principal's sole unrestricted Company grant. New caller ownership/provider claims are rejected. Creator-owned private uploads bind their actual bytes and SHA256. A freshly authorized Approver can link same-company parents once, through POST, without replacing parents or rewriting provenance. File validation after Frappe normalization prevents insert, update and duplicate-upload aliases from changing source ownership. Historical unbound rows remain unknown.

| Principal or attempted action | Native result |
|---|---|
| Guest, Supplier or mixed Supplier/Accounts | Denied; Supplier precedence retained. |
| Enabled Salesperson, one Company grant | Authorized manual source creation/capture and permitted previews. |
| Approver, same Company and current parent permission | Controlled review/link; stale revisions or replaced/foreign parents denied. |
| Accounts | Permitted applicable read/report operations; restricted creation/history operations stay restricted. |
| Other Company, ambiguous/revoked grant, disabled user, forged Company/session principal | Denied without authorized business posting. |
| DocShare, selected export, direct/v2 reads, private source/file aliases | Fenced by fresh principal, source binding and parent permission. |
| Administrator/import or legacy unbound sources | No inferred tenant ownership; legacy compatibility remains an explicit limitation. |

Cloud native tests ran against the installed candidate: **12/12 unit tests, 30.824s; 19/19 authenticated WSGI/HTTP tests, 132.204s**. The separate WSL upgrade proof preserved all **456** original Evidence identities/fields and left all new ownership values NULL through two migrations. The additive Data field and eighth registered proof do not backfill historical ownership.

One cloud HTTP attempt ran while assets/fixtures were still changing and failed; the full serialized run after setup passed. Failures are retained privately. Authentication or assertions were not weakened to obtain success. Provider ingress, legacy ownership assignment and full production security certification remain outside this narrow acceptance.

## C. Reporting and real spreadsheets

Actual deployed Stock, Sales and Receivables endpoints and CSV exports passed **11/11 native HTTPS API cases**, including Guest, Supplier, mixed-role and other-company denial. Final desktop/mobile Playwright verification after service isolation passed **7/7 in 78.106s**: six positive report/export cases and an actual other-company browser denial. Each case retains screenshots, a WebM recording and a trace.

Six actual downloaded CSVs independently passed Decimal checks:

| Report | Synthetic acceptance result |
|---|---|
| Stock | Operating inward 100 − posted outward 25 = remaining 75 Kg; opening inventory UNKNOWN. |
| Sales | Verified LOT-A; approved and allocated quantity 25; 25 × INR1,000 = INR25,000. |
| Receivables | INR25,000 − INR10,000 applied − INR0 noncash adjustment = INR15,000 outstanding. |
| Pending receipt | INR5,000 remains `AUTHORIZATION_INPROCESS`, `BANK_PENDING_NOT_CLEARED`; application/outstanding attribution remains UNKNOWN. |

Missing evidence is not substituted with zero. Bank-pending is not bank-cleared. These fictional receipts verify accounting treatment, not a real bank transaction. The lot correction follows the actual Container child reference; foreign or unresolved references remain UNKNOWN.

Five actual XLSX versions were fetched privately and reconciled read-only. Plum: 62 selected sales rows, quantity 2,737, amount INR2,307,400. Grapes: 76 rows, quantity 2,876, amount INR4,172,700. The fetched CA workbook's selected totals reconcile INR7,070,490 sales − INR5,980,093 allocations = INR1,090,397 receivable. These are source-workbook figures, not approved Fresko ledger truth.

None of the five downloaded versions matches its reviewed fixture hash/range contract. One Plum version also has physical balance 85 where the reviewed cutoff fixture expected zero. **SOURCE_VERSION_DRIFT** therefore remains open; reviewed hashes were not rewritten and no bank clearance, physical stock finality or posting authority was inferred. This is not an inventory of every Fresko source file. Originals, extraction details and source hashes remain in the owner's private local real-data directory; no real workbook or customer transaction row is included in the shared QA archive.

Live LLM/OCR/WhatsApp ingestion and broader feature development remain deferred under the MVP scope.

## D. Google Cloud

Project `project-86f9787f-03f9-4f7e-b10`; region `asia-south1`, zone `asia-south1-a`; existing instance `fresko-staging-vm`, e2-medium/4GB RAM, 60GB balanced persistent disk, existing static IP `34.93.162.135`. No extra VM, disk, IP, GPU, snapshot, load balancer, managed database or paid scheduler was created.

The original site initially had 145 Evidence records and no disposable markers. It was preserved. The new site uses `/home/freskoqa/fresko-private-staging-20261017`, its own source and fresh environment, separate MariaDB datadir/socket/port 17306, Redis ports 17100/17200, two web workers at loopback 18081, one queue worker and private HTTPS at loopback 18443. All three disposable/fixture/test markers are required before synthetic writes.

Runtime: Frappe **15.120.1**, pinned `9f8ae9cd25b6735be345da6cc12e9f5a96050c68`; ERPNext **15.121.2**, pinned `df8b7f9648c2ec4da12db8c4022edc8dd1018c6b`; Python **3.11.17**; Node **18.20.8**; Yarn **1.22.22**; MariaDB **10.6.23**; Redis **7.2.16**; Gunicorn **23.0.0**. Fresh browser assets were built from pinned source/frozen lockfiles; 41 bundles checked. Old environments/assets were not adopted.

Private access is authenticated SSH through IAP, forwarding local port 19043 to VM loopback 18443. The tested browser origin is `https://fresko-staging.34.93.162.135.sslip.io:19043`, with a browser-local resolver mapping this hostname to 127.0.0.1. Certificate verification remained enabled. Both original and private site health checks returned HTTP200; SSL verification returned 0.

The original public 80/443 and IAP SSH firewall settings were preserved. New application services cannot read `/home/frappe` in their mount namespaces, cannot open new connections to old loopback services, and cannot reach cloud metadata. Replies to established connections and new owned service ports remain permitted. Root-run shutdown/network scripts and HTTPS configuration are under root-owned `/usr/local/lib/freskoqa-staging`; the app cannot replace them. These protections were checked against the running app namespace and rerun through actual HTTP/browser workflows.

The existing VM service-account IAM has an overbroad Compute role; it was not broadened or rewritten. A direct service-account API stop permission check returned 403, so that proposed mechanism was not installed. The accepted deadline uses Google's documented clean guest shutdown and needs no new token or IAM grant.

Billing is enabled. The user attests adequate credits. Exact remaining credit, promotional expiry time, current spending and Free Trial versus paid continuation remain **UNKNOWN** because the connected CLI did not expose them. Original planning envelope was USD100; the lead used a narrower USD25 additional-work bound and reused existing resources. An exact invoice or zero-cost claim is not supported.

## E. Recovery and shutdown

The initial full WSL backup was preserved privately before the schema change. Separate WSL restore/two-migration comparison passed for all 456 historical Evidence rows.

The new cloud site's four backup components—database, public files, private files and config—were restored to new disposable databases in its separate cluster. Business rows, roles, permissions and **40 file hashes** survived two migrations. Independent comparison covered **all 26 Fresko DocTypes plus File, Has Role and User Permission**. A second recovery proof generated a synthetic encrypted secret, preserved the source encryption key and successfully decrypted that secret after both restored migrations. Database/config/encryption keys were never included in the shared evidence.

Both full recovery bundles were copied off the VM to the owner's private local directory and each of the four component lengths/SHA256 values was independently verified. Final component hashes and row counts are in `cloud_recovery_key_checkpoint.json` and `cloud_recovery_key_all_doctypes_checkpoint.json`. Private backup: `/home/dshri/.local/state/fresko-control/gcp/cloud-secrets/full-synthetic-key-recovery.tar.gz`.

To withdraw only the new staging workload, run on the VM:

```sh
sudo systemctl start freskoqa-staging-shutdown.service
```

That exact action was rehearsed: all six new workload services stopped, the original HTTPS site stayed healthy, the new services resumed and API checks passed. It does not restore or downgrade the original site's database. Full rollback for a new candidate uses a new disposable restore destination and the pinned source/config bundle, not overwrite of unknown business data.

The disposable shutdown timer and the separately approved **whole-VM clean shutdown timer** are enabled for **17 October 2026 at 23:59 India time (18:29 UTC)**. Root execution, exact VM identity, protected script ownership and timer's next firing were verified without shutting down the VM now. The user's instruction “whatever you think is best” authorized the whole-VM decision. Actual future firing has not yet occurred; the guest timer depends on the VM OS/clock remaining operational.

The whole VM will stop, including the original site, while disk/IP are retained. [Google documents clean guest shutdown and continuing attached-resource costs](https://docs.cloud.google.com/compute/docs/instances/stop-start-instance). Stopping does not eliminate disk or reserved-IP charges. Deletion/release of those resources is not authorized by this delivery. For continuation, inspect and deliberately disable/replace expired deadline controls before resuming paid work.

## F. QA evidence and handoff

The shared evidence includes exact-SHA CI references, source archive/hash, nonsecret deployed control files and their manifest, API/browser result manifests, independent CSV reconciliation, restore hashes/counts, isolation proof, shutdown proof, screenshots, actual WebM recordings and sanitized trace copies. Raw traces, credentials, SQL and config backups remain private. Trace copies were scanned and stripped of passwords, session/cookie/CSRF values and request bodies; raw originals were retained.

Successful command exit codes: site install 0; two migrations 0; native wrapper 12/12 and serialized HTTP 19/19 0; API checks 11/11 0; final browser 7/7 0; six-CSV Decimal verification 0; both restores/two migrations 0; all-26-DocType comparison 0; service isolation proof 0; disposable stop/resume rehearsal 0; whole-VM timer setup/check 0. Frappe's test command can return 0 despite test failures, so Ran/OK/FAILED content was explicitly checked.

Earlier failed setup/rendering/connection and overlapping-test runs remain recorded as failures. A worker bootstrap draft contained a potential credential string and unsafe adoption steps. It was rejected, redacted and quarantined; validity of that string is UNKNOWN, no old database credential rotation is claimed, and the insecure bootstrap was not used. A subsequent optional independent security review was rejected by OpenAI's Daybreak access check; it was not retried to bypass the restriction. Other authorized work continued. Flash's later quota exhaustion was a separate 429 limit.

The original WSL QA app link was returned to `/mnt/c/Users/dshri/Downloads/fresko-mvp-integration/fresko_universe`, its original source was preserved and the QA login returned HTTP200. Its additive schema and private pre-change backup remain recorded. The accepted candidate is the separate cloud site, not that restored historical WSL source.

Windows desktop browser initialization was unavailable. Native Google Sheets values/format/validation/hyperlinks can be checked through the connector; visual fit of the Sheet UI is not claimed. Linux native Chromium proves desktop/mobile viewport behavior, not a physical mobile device.

## G. Release classification and owners

**CONDITIONAL GO — the exact candidate is accepted for private synthetic staging and demonstration within the exercised gates.** No known P0 remains in those exercised gates; green tests do not establish universal security, production readiness or approved real-data balances.

| Priority | Remaining issue | Owner |
|---|---|---|
| P1 before real business use | Resolve source version/cutoff drift; authorize source-to-ledger mappings and bank/stock evidence. | Fresko business owner and accounts/CA reviewer. |
| P1 before legacy migration | Historical unbound ownership and original cloud data classification remain UNKNOWN. | Fresko owner with integration/security lead. |
| P1 financial follow-up | Exact credits/expiry/paid behavior and retained disk/IP charges remain unknown; authorize eventual preservation or cleanup. | GCP billing owner. |
| P1 legacy posture | Review overbroad legacy IAM and assess the rejected draft's potential credential exposure; no rotation or full old-site security certification is claimed. | GCP/security owner. |
| P2 assurance | Optional independent cloud security review remains unavailable after Daybreak rejection. | Platform access owner/security reviewer. |
| P2 usability/coverage | Test the owner's Windows private-access workflow and physical mobile device; broader provider/live ingestion remains deferred. | QA/product owner. |

## Private access instructions

Keep the authenticated tunnel running in a terminal on the owner's machine:

```sh
gcloud compute ssh fresko-staging-vm --project=project-86f9787f-03f9-4f7e-b10 --zone=asia-south1-a --tunnel-through-iap -- -N -L 19043:127.0.0.1:18443
```

Open a dedicated Chrome profile with resolver arguments, then visit the tested private origin:

```text
chrome --user-data-dir=<private-QA-profile-directory> --host-resolver-rules="MAP fresko-staging.34.93.162.135.sslip.io 127.0.0.1" --no-proxy-server https://fresko-staging.34.93.162.135.sslip.io:19043/app/fresko-reports
```

The explicit resolver is necessary because ordinary DNS points to the original public IP. The actual Linux Playwright workflow above was tested; these owner's-machine launch instructions have not been visually verified on Windows. QA login is `group1b-http-accounts@example.invalid`; its private password is retained locally in `/home/dshri/.local/state/fresko-control/gcp/cloud-secrets/qa_reporting_credentials.json`, outside git and all shared archives.

## Application files changed since the preserved Flash baseline

- `.github/workflows/ci.yml`
- `docs/AGENT_HANDOFF.md`
- `fresko_universe/fresko_universe/evidence_scope.py`
- `fresko_universe/fresko_universe/fresko_core/doctype/fresko_evidence/fresko_evidence.json`
- `fresko_universe/fresko_universe/fresko_core/doctype/fresko_evidence/fresko_evidence.py`
- `fresko_universe/fresko_universe/hooks.py`
- `fresko_universe/fresko_universe/intake_native.py`
- `fresko_universe/fresko_universe/permissions.py`
- `fresko_universe/fresko_universe/reporting_engine.py`
- `fresko_universe/fresko_universe/tests/test_fsec_permissions.py`
- `fresko_universe/fresko_universe/tests/test_intake_http_group1b.py`
- `fresko_universe/tests/test_reporting_engine_offline.py`
- `scripts/prove_unassigned_evidence_upgrade.py`
- `scripts/rotate_qa_credentials.py`
- `scripts/run_native_browser_tests.py`
- `scripts/run_native_http_reporting_tests.py`
- `scripts/schema_migration_proofs.json`
- `scripts/schema_snapshot.json`
- `scripts/seed_reporting_acceptance_data.py`
- `scripts/test_schema_migration_harness.py`
- `scripts/verify_reporting_csv.py`
