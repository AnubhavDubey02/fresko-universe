# Group 1B authenticated intake runtime

The adapter stores review proposals, never Physical, Commercial or Money truth.
Its starting source is PR22 `cf05fb145c8135fb3cfa40a01c79f4bb75566a29`.
Batch4 ZIP SHA256 is `591b55734d303636b9cb76e9618d90a4f77259fa865fdc8ed15d024a060c2502`.
The additive source was reviewed against actual hooks; the reconstructed hooks
patch did not apply and was not substituted for existing authorization hooks.

## Authority and channels

`intake_native.capture` accepts Evidence name, channel, qualified locator and
proposed fields. It rejects extra tenant/role/verified authority. Frappe's exact
RPC `cmd` marker is transport metadata, not authority. Enabled User, current
roles and Company User Permissions are read from MariaDB, independently of
cached session roles. Supplier precedence always denies. An actor must have an
internal Fresko role and exactly one unrestricted Company grant. Ambiguous,
missing, disabled or revoked authority fails closed; System Manager alone does
not grant business authority.

All four channels use Group1A's exact-value/UNKNOWN contract. Provider channels
require all stored provider/account/conversation/event identifiers and cannot
fall back to the legacy unscoped path. This is stored-Evidence integration, not
live WhatsApp provider signature verification or an OCR/Excel import pipeline.
Manual notes are rehashed; private file sources require permitted Evidence and
linked parents, canonical File authorization, path containment and actual byte
SHA256 readback. Candidate field proposals never verify underlying business facts.

## Persistence and transactions

Fresko Intake Draft has unique proposal_key, immutable initial fingerprint,
company, source reference, current_revision and version. Fresko Intake Revision
has unique revision_key and draft:sequence key, predecessor, actor, reason,
source and immutable payload. Only the service can create these documents;
generic writes, rename and deletion are denied. Unknown values stay null.

Capture serializes by deterministic proposal identity with a MariaDB advisory
lock retained through the owning transaction's commit/rollback, then uses current
row locks. Review uses the same serialization key. No service commit occurs.
Identical delivery produces one draft/revision; changed content adds a durable
sticky conflict. Content under another event is marked possible duplicate, not
merged. A failure between draft and revision is rolled back to the savepoint;
MariaDB deadlocks propagate without attempting a nonexistent savepoint rollback.

Review supports ACKNOWLEDGE, REQUEST_EVIDENCE and REJECT, with separate Accounts
or Approver actor, reason and explicit current version. It is acknowledgement,
not sale/money approval or posting. Blank/stale tokens fail. Fresh authorization
is repeated after acquiring the draft lock. History remains append-only.

## Read and attachment isolation

Every draft read rechecks company, original and revision Evidence permissions.
Direct-ID, list/count, v1/v2 and controller paths are fenced before framework
DocShare fallback. Unreadable and missing intake IDs receive generic denial.
Private File downloads, RPC aliases, ZIP export, owned aliases and list APIs
resolve durable source URL provenance. Ownership/sharing cannot override tenant
or Evidence denial. The three pinned File list endpoints retain their response
contracts and apply explicit tenant filters before pagination and counts.

Intake source File privacy/location/binding and Evidence provenance cannot be
changed or deleted through normal document operations. File protection runs
before_validate, ahead of Frappe filesystem moves. Generic File controller
mutation calls are denied for intake bytes. Corrections attach new Evidence and
append a revision. Cross-company reuse of one protected URL currently fails
closed; an explicit source-sharing contract is future work.

## Evidence and limits

Native tests use a new synthetic-only WSL site, pinned Frappe
`9f8ae9cd25b6735be345da6cc12e9f5a96050c68`, ERPNext
`df8b7f9648c2ec4da12db8c4022edc8dd1018c6b`, MariaDB10.6 and Python3.11.
Authenticated WSGI tests exercise genuine login/cookies/CSRF, request routing,
permissions and commits. They are distinct from external browser/device proof.
Threaded replay tests use separate MariaDB connections and independent committed
reads. Exact-head CI and immutable evidence are recorded in the Draft PR.

Migration proof `unified_intake_drafts` is the seventh registry proof. Exact
PR22-to-candidate first and repeated migrations preserve legacy values and create
zero intake rows; CI also executes the seeded Phase1 registry proofs.

Draft list ACLs conservatively examine linked source history. URL provenance is
batched per inspection, but large-history/pagination load certification remains
pending. No high-volume latency claim is made. Native tests do not certify live
provider signatures, workbook mapping, an intake browser UI, physical devices,
external staging, production or the complete RG-16 pilot gate. Independent review
and combined exact-source staging approval remain required; production is NO-GO.
