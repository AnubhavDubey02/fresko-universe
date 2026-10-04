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
created at that checkpoint; recovery must run again after browser finance flows.
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
remains required before claiming browser acceptance.

A delayed Workspace response could also repopulate a Container after its filter
was cleared. Clearing the filter now advances the request generation before
returning and discards the old selection and response. Offline behavioral tests
cover both read races; they do not substitute for the real browser checks.

Defer broad operator UX to the next bounded packet: mobile table/control access,
clearer raw-lot guidance, actionable permission-aware buttons, removal of stale
Money-extension copy and unified contextual pending/exception presentation.
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
