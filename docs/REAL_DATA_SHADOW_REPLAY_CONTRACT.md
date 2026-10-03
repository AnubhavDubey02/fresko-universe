# Real-data shadow replay contract

Sanitized deterministic acceptance gate while Excel remains operational source of truth. Not runtime proof, accounting posting, or source-workbook replacement. Assertions use `SOURCE_OBSERVED`, `USER_CONFIRMED`, `DERIVED_ARITHMETIC`, `UNKNOWN`, or `PENDING`; unknown is never zero or approval. Operating and declared quantities are separate; pending DO never reduces stock. GP205537 remains 80 lot 42076 plus 20 lot 42074; rate buckets are not mapped to GPs.

INR 101 is a labour outflow and contributes zero to collections. INR 350,000 remains `PENDING_EVIDENCE_BINDING` in the fixture until exact bank Evidence is attached; received, cleared, and allocated remain distinct. `92 × 700 = 64,400` remains `VERIFICATION_PENDING` until exact photo evidence and role approval are linked. The validator checks fixture assertions only; passing does not prove production, bank, source, or CA truth.

Source workbook binaries stay outside the repository. Each workbook entry is
pinned by its reviewed SHA-256 and declared used ranges, and every replay points
to one of those ranges. The handwritten photo is intentionally recorded
as a pending source with no fabricated hash until the exact image is linked.
Activation of the 92-at-700 assertion requires both a verified photo hash and
role approval.

The gate passes only when source identities, cut-offs, quantities, pricing,
allocations, collections, receivables, and classification boundaries reconcile
deterministically. It fails on missing/unknown sources, hash/range drift,
declared-versus-operating conflation, pending-DO stock effects, invented
GP-to-rate allocation, unsupported 92 activation, or collection/allocation
arithmetic drift. A pass proves fixture consistency only; it does not prove
runtime ingestion, database persistence, bank clearance, accounting treatment,
legal disclosure, or CA sign-off.
