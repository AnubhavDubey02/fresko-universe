# Implementation 02: staging package and browser baseline

Base: post-PR17 main `104c488fa0765a7b13b1c99d553b3be65b36c848`.
Scope: deployment packaging, native browser acceptance and recovery evidence.
No WhatsApp, OCR, MCP, production deployment or operator redesign is authorized
by this packet. A CI browser site is not Frappe Cloud staging proof.

## Package boundary

The development repository remains a monorepo. Its installable app is
`fresko_universe/`; adding a root metadata shim would conceal the wrong Bench
app/package layout. `scripts/export_deployment_app.py` instead exports all
tracked app files from a full immutable source SHA into a normal app-root
directory. It reads Git blobs, never working-tree changes, rejects symlinks,
gitlinks and unsafe paths, and publishes with an atomic no-replace rename.
The preparation tool requires Linux and Python 3.11+. This does not change the
application's Python requirement.

`FRESKO_DEPLOYMENT_MANIFEST.json` records the canonical source repository,
source commit, app subtree and every file's hash, size and executable mode.
The repository origin must match the canonical Fresko repository. Exported
files retain their source bytes. The manifest has no timestamps or credentials.

The app's own `pyproject.toml` declares Frappe and ERPNext compatibility
`>=15.0.0,<16.0.0` under `[tool.bench.frappe-dependencies]`. These are framework
compatibility declarations, not PyPI application dependencies. Existing
`required_apps` hooks remain authoritative for ERPNext installation. The Flit
build backend is pinned to 3.12.0. Application `dependencies = []` remains.

The intended Cloud source is an immutable **app-root deployment branch** in the
existing GitHub repository, named `codex/deploy-<full-source-SHA>`. This preserves
main's monorepo layout and avoids another repository. Its independent deployment
commit must be recorded alongside the source SHA and manifest subtree hash.
Never force-push or advance an existing deployment ref. Publish only the export
of the independently reviewed, exact-head green candidate. Selecting a branch
in Cloud and validating its metadata is a live deployment checkpoint, not proof
supplied by these files.

CI exercises `bench get-app file://<exported-Git-app-root>` followed by fresh
installation, migration, all application tests and all existing upgrade gates.
Historical baseline sources still use their existing migration-proof paths.
No persisted DocType schema is changed by this packet.

Local preparation commit `26f8cd51702786f662d8a7a8ba0a9c4710a8ae1c` passed
fresh-site install/migrate and 275 pinned Bench tests (zero failures/errors),
228 app/static tests, 49 script tests and both Node UI harnesses. The local
Bench used the synchronized app copy; GitHub additionally tests immutable
export and normal `bench get-app`. Native acceptance, exact-head CI and Cloud
deployment have distinct gates and are not inferred from these results.

## Platform pins and actual deployment identity

| Component | Required test pin |
|---|---|
| Frappe | v15.120.1 / `9f8ae9cd25b6735be345da6cc12e9f5a96050c68` |
| ERPNext | v15.121.2 / `df8b7f9648c2ec4da12db8c4022edc8dd1018c6b` |
| Python / Node / MariaDB | 3.11 / 18 / 10.6 |
| Fresko | app version 0.0.1 plus immutable source and deployment commits |
| Browser harness | Playwright Python 1.61.0 and its matching Chromium |

Record **actual** Cloud deploy IDs, app commits, runtime versions, site URL,
region and verification times after deployment. A v15 label does not prove an
exact SHA. Cloud supports custom framework forks; if its default v15 releases
cannot match approved pins, prepare fixed source branches/forks rather than
silently testing different framework versions. Do not assume a supported range
pins a deployment. Confirm dependencies in the bench dashboard before deploy.

## Account connection and billing checkpoint

Official Cloud documentation checked on 2026-10-04:

- [Private benches](https://docs.frappe.io/cloud/benches): custom apps require a
  private bench; private-bench sites require USD 25/month or higher plans and a
  payment method. Creating a bench group alone is not site billing.
- [Root metadata and versioning](https://docs.frappe.io/cloud/custom-apps/app-versioning/versioning).
- [Create a private bench](https://docs.frappe.io/cloud/benches/create-new).
- [Custom framework source](https://docs.frappe.io/cloud/benches/custom-app).
- [Deployment versions](https://docs.frappe.io/cloud/benches/updating_a_bench).

The user has no existing staging site and has explicitly withheld authority to
make a paid purchase. Prepare the reviewed package first. Then the user should:

1. Create or sign into a Frappe Cloud account. Use a separate staging bench/team
   context; do not connect an existing production/pilot site.
2. Connect the Cloud GitHub application with access limited to the Fresko
   repository. Do not paste passwords, API tokens or cookies into chat.
3. Provide the account/team name and confirm the proposed staging-only site
   name. Account login can be completed in the connected browser; scoped SSH
   access can be configured after the private bench exists.
4. Inspect the current plan, region, taxes and displayed price. **Approve the
   exact paid staging-site cost before adding billing or creating that site.**
   The cited USD 25 floor is not a final invoice quote.
5. Create a private v15 bench group named for staging. Choose the region based
   on the user's operations/data requirements. Add ERPNext and Fresko using the
   reviewed immutable app-root deployment branch. Validate source SHAs and
   Python/Node versions before clicking Deploy.
6. Deploy the bench group, inspect app versions in its Deploy record, then
   create a fresh staging site inside that bench with ERPNext and Fresko.
   Keep auto-update/auto-deploy disabled for this immutable acceptance release.
7. Supply the new staging URL and connected access. The integration owner then
   runs install/migrate verification, role provisioning, native browser flows,
   version capture and backup/restore checks. Reachability alone is not green.

If the hosting UI/API cannot select the required app source/version, stop that
dependent deployment step and report the exact limitation. Do not float pins or
make a production change. No deployment or Cloud account access is claimed
until actual provider evidence exists.

After the private bench exists, configure access using the current
[Cloud SSH procedure](https://docs.frappe.io/cloud/benches/ssh): add an OpenSSH
public key in Account Settings, open the bench's SSH Access action, generate
its six-hour certificate and run the two commands shown by that dashboard in
WSL/Linux. Keep the private key and certificate local. Share the staging URL
and team/bench names here, never key material. The proxy does not support SCP;
do not expose private files through public web paths to work around it. Run
Playwright from the verification machine against the authorized staging origin;
do not assume hosting allows installation of browser system packages.

## Browser and credential boundaries

`scripts/browser_acceptance.py` runs real native Frappe pages and dialogs through
six independently authenticated users. It never mocks successful server
responses. Explicit API calls are reads, replay checks and adversarial checks;
they do not replace happy-path UI actions. Three viewport scenarios use 1280,
390 and 360 CSS pixels. Mobile emulation includes touch capability; **a physical
touch-device pass remains separate and pending** until performed on a device.

`scripts/ci_browser.sh` is only for an already marked disposable local CI site,
with `allow_tests`, a pre-existing `fresko_disposable_browser_site` flag, and a
loopback browser origin. It refuses arbitrary remote origins. The nonwhitelisted
fixture seeder additionally requires Administrator, an explicit fixture flag,
a new outside-bench private manifest and an unseeded site. These flags must
never be enabled on production or a site holding financial/pilot truth.
Before installing or rewriting bench configuration, `scripts/ci_bench.sh` also
refuses existing sites without the disposable marker and symlinked bench/site
paths. Its hosted workflow uses a new ephemeral bench; neither CI launcher is
a staging or production deployment command.

The seed creates a separate synthetic Company, masters, six users, three pairs
of Containers, source Notes and posted Outwards. The manifest contains random
test credentials and is mode 0600. It lives outside Git and public artifacts.
Cleanup is registered before secret-bearing work. Screenshots are taken only
after authentication on synthetic domain pages. No cookies, storage-state,
HARs or raw Playwright traces are published. Public summaries omit exception
payloads; private diagnostics redact known test passwords.

For Cloud verification, use the standalone suite only against explicitly
authorized synthetic staging fixtures. Do not run the loopback CI launcher as
a production infrastructure recipe. Disable test/fixture flags before any
subsequent operator or pilot use.

### Prepared physical touch-device pass

After hosting access is connected, open the authorized staging URL on one real
Android/Chrome or iPhone/Safari device. Record device, OS/browser versions,
viewport, UTC time and deployed app SHAs. Use a fresh authorized synthetic
scenario so repeated allocation attempts cannot consume a previous scenario's
remaining quantity. Never substitute existing pilot records.

Follow the same multi-lot Sale, alias/rate review, Outward allocation, Collection
and Payment Allocation sequence using separate maker, verifier and approver
accounts. Check tapping, scrolling, dialog fields, mobile tables and Container /
As Of switching; repeat a slow or double-tapped action and confirm its single
persisted result. Check Supplier and mixed-role direct URL denial. Capture only
synthetic domain screens after login and record pass/fail per action; exclude
credentials and session material. Device/emulated evidence remain separately
labelled. This protocol is prepared; no physical-device execution is claimed.

## Recovery proof and Cloud completion

`scripts/browser_recovery.py` creates a full database/public/private/config
backup of the explicitly synthetic local site and restores it into a new random
local site. It compares selected protected fixture records, public/private file
sentinel bytes and an encrypted-secret sentinel after migration. The resulting
summary names the compared scope and counts; it does not claim full database
or entire filesystem byte equality. The local restore site is retained for
inspection and must be cleaned with its exact generated name after review.
The first local run passed after creating an empty destination site before
restore. Its snapshot included two draft Sales, six Containers, three posted
Outwards, both file sentinels and the decrypted secret. Money rows were not yet
created at that checkpoint. The later post-Money recovery passed with one
approved Collection, one approved Payment Allocation, five Sales, six Containers,
three Outwards, one alias mapping and three Outward allocations, plus both file
sentinels and encrypted-secret readback. These are selected synthetic records;
the proof still does not establish whole-database equality or Cloud recovery.
Failed synthetic destinations are identified by their generated name in the
error/private diagnostic and require exact-name cleanup. No source-site restore
or deletion is performed. The local MariaDB account scope is an isolated test
runner setting, not a hosting configuration recommendation.

This isolated-runner proof is not a Cloud backup. After staging is connected:

1. Create a Cloud on-demand full backup and record its provider ID/time, deployed
   versions and four components (database, public files, private files, site
   configuration/encryption keys). Keep backups and key material private.
2. Restore into a separate authorized disposable site/bench with compatible
   pinned app versions. Any additional paid restore site requires explicit
   cost approval. Never restore over the staging source or a pilot site.
3. Preserve the destination's database credentials while restoring the source
   encryption keys. Prove private/public readback, encrypted-field decryption,
   protected record snapshots and authenticated browser access.
4. Record restore ID, duration, result and cleanup. If the plan forbids a
   complete restore or access is unavailable, record that exact limitation;
   do not label a backup download as a successful restore.

[Cloud backups](https://docs.frappe.io/cloud/sites/backups) and
[restore components](https://docs.frappe.io/cloud/sites/migrate-an-existing-site)
govern the hosting procedure. The existing local/CI Compose is never production
infrastructure.

## Browser defects and next bounded packet

Reproduced repairs in this packet:

- Both Pages erased their native filter form after creating controls. Append
  domain content without removing the native form.
- Sale-Outward queue queried nonexistent `status` and `source_event_id` fields.
  Query `state`, verification actors and `source_event_key`; derive the review
  label from actual verification fields without adding a persisted state.
- Sale actions consumed a historical projection without a version. Frappe
  serializes JavaScript null as a blank form token, causing `STALE_VERSION`.
  Blank cutoff now selects Live state with `current_version`; explicit cutoffs
  are read-only audit projections with `version_at_cutoff`. HTTP mutation tokens
  fail closed; trusted direct Python compatibility is preserved. The exact
  contract is in `COMMERCIAL_SALE_RUNTIME.md`; stored audit snapshots do not change.

The Money read lock also suppressed a new filter request while the old request
was pending. The Node regression reproduced this. Reads now run independently,
and callbacks check filter context and request generation before rendering.
Duplicate writes remain serialized. Delayed **real** browser response evidence
now passes locally for both Pages: the harness holds an actual successful
server response, changes the native cutoff, then releases the old response and
asserts that the newer projection remains displayed. It also holds a Workspace
response across a native Container change and waits for completed callbacks.
The Money race runs after the financial workflows and requires distinct actual
old/new sales counts, so an empty fixture cannot satisfy that proof. Fresh
exact-head CI still must run these checks with the complete desktop/mobile workflows.

Native Link `get_value()` can reflect input before server validation and the
filter change callback finish. The browser helper waits for committed Control
state before querying; it does not use a fixed delay. Pristine completed fixture
debt is INR 4000 for one Container and INR 12000 for the shared Customer. Unpriced
Sale PENDING is checked before late-rate approval, separately from those known
positions. Prior unpriced drafts on a reused local site do not define fresh CI
expectations.

A delayed Workspace response could also repopulate a Container after its filter
was cleared. Clearing the filter now advances the request generation before
returning and discards the old selection and response. Offline behavioral tests
cover both read races; they do not substitute for the real browser checks.

The completed harness also replays the exact native Collection create request,
checks the original record identity and one persisted source-event row, checks
historical read-only controls and stale-token truth equality, and rejects missing
required saved workflow IDs or skipped acceptance tests. Supplier and mixed-role
native URL/API denial passed locally. Artifact output must be a new nonsymlink
directory; a rejected destination is never used for the summary either. These
focused results do not establish a complete desktop/mobile or hosting pass.

A native 360px reproduction also found that tabbing from Customer opens the
Collection Datetime picker; Escape dismissed the parent dialog too. The helper
now clicks the visible dialog heading to dismiss that picker while retaining
the selected Customer. Page-level picker dismissal remains separate. A native
read-only regression checks both the Page Container Link and this dialog path.

Defer broad operator UX to the next bounded packet: mobile table/control access,
clearer raw-lot guidance, actionable permission-aware buttons, removal of stale
Money-extension copy and unified contextual pending/exception presentation.
The native narrow-screen `New Collection` primary button also lacks an accessible
name when its text is hidden; the harness uses its visible `data-label` button.
Workspace inner actions are reachable through Frappe's native mobile Menu links,
which the harness follows instead of interacting with hidden desktop buttons.
Record actual screenshots/findings before ranking this work. Do not start that
packet until this packet's available gates and independent review are green.

## Delegation and measured usage

| Worker | Assigned work | Available usage measurement |
|---|---|---|
| Gemini 3.8 Flash medium | Bounded immutable package exporter/tests | Reported 39,135 tokens; 84.2 seconds |
| Gemini 3.8 Flash low | Native browser helper draft | Reported 21,779 tokens; 52.63 seconds |
| Gemini 3.8 Flash medium | Commercial version command attempt | Reported 126,175 tokens; 85.36 seconds; RunCommand denied, zero applied edits |
| Luna | Independent security/source review, native UI diagnosis and bounded browser completion | Per-agent token/quota measurement unavailable |
| Codex integration owner | Frappe failures, minimal runtime fixes, verification and CI | Shared account allowance only; no per-agent attribution |
| Astra | Read-only Commercial live/history token contract design after a reproduced browser failure | Per-agent token/quota measurement unavailable |

Provider token reports are separate from Codex quota percentages; no monetary
cost is inferred. Flash invocations have roughly 20,000 input tokens of overhead,
so cohesive bounded briefs conserve more than repeated tiny calls. Observed
weaknesses: generated delimiter escaping needed correction, native autocomplete
and popup timing required actual browser diagnosis, and static review missed the
native Page filter lifecycle. Assign implementation with explicit contracts and
retain independent review plus actual runtime gates.
Existing durable test fixtures also collide when the complete Bench suite is
rerun on the same site. Complete gates use a fresh isolated site; repeated
browser workflows retain their partial records instead of deleting posted truth.
Inspect native CLI `denied_actions` and the actual diff: a `SUCCESS` envelope and
exit zero did not prove command execution. Avoid repeating command-based Flash
delegation until that capability is resolved; integration owner applied this
repair after the bounded attempt was denied.

## 2026-10-06 GCP staging and supplier HTTP closure addendum

The earlier Frappe Cloud setup and billing steps above record the original plan.
The approved staging deployment instead ran on the dedicated GCP VM
`fresko-staging-vm` in `asia-south1-a`, project
`project-86f9787f-03f9-4f7e-b10`, at
`https://fresko-staging.34.93.162.135.sslip.io`. This is a staging-only
synthetic site. The 2026-10-05 proof used source
`f593990dc3457bfa5c54e9c0524c2f7cd974cd11` and exported app commit
`afea097fe5ada1e1f390e4b6b12daf08ee6876ba`; it does not prove any
later source or deployment commit. Frappe was pinned to
`9f8ae9cd25b6735be345da6cc12e9f5a96050c68` and ERPNext to
`df8b7f9648c2ec4da12db8c4022edc8dd1018c6b`.

The 2026-10-05 site passed 275 Bench tests and seven external browser tests
across 1280, 390 and 360 pixel viewports. A GCS object was downloaded and
round-trip decrypted, and a separate four-component backup was restored into
an isolated site with selected protected records and file sentinels equal.
The GCS roundtrip and isolated restore are separate proofs. The original
restore sites are archived for inspection. A local backup runs every six
hours; encrypted off-VM replication remains manual. Reboot recovery is
supported by configuration evidence but has not been exercised by a reboot.
The physical-device touch pass remains pending.

Network access uses a dedicated VPC, public HTTP/HTTPS 80/443, and IAP-only
SSH from `35.235.240.0/20`. MariaDB and Redis bind to loopback. The VM
service account has logging/monitoring writes, bucket-scoped objectCreator
and objectViewer, and access to the named backup-key secret. The GCS bucket
enforces public access prevention. No project-wide Viewer grant is needed.

A live check on the prior deployed source reproduced a Supplier precedence
defect: a mixed Supplier+Accounts identity could list 14 Evidence Attachments
and 45 Evidence Attempts (HTTP 200) while individual reads were denied.
The bounded source repair adds an Frappe `auth_hooks` guard after authentication
and before dispatch, denying authenticated identities with any Supplier role,
including Administrator, at internal HTTP endpoints. Only exact login, logout
and current-user requests are allowed for those identities. Evidence child
list/document hooks also deny mixed Supplier roles; their Administrator
exception retains trusted offline bootstrap behavior. A new source commit
requires exact-head CI and a new immutable app export, followed by live
Supplier/API-key, Accounts/private-file and operator denial checks before
the security closure is claimed. The earlier 2026-10-05 browser/Bench proof
must not be applied to the repaired source.

The three previously exposed staging operator credentials have a private
owner-only handoff. Any scoped password proof must verify old-password
failure, current-password success and only its own new-session logout without
printing credentials or changing further accounts. Keep the recoverable
owner-only rotation vault. Staging flags and service state need a fresh
read-only check after security deployment; the latest values must be recorded
with the final source and app export identities.