# WhatsApp readiness fixtures

These compact JSON cases are Phase 1 closeout evidence for planning and testing
a future Phase 2 ingestion boundary. They are not imported by the Fresko app and
do not authorize Phase 2.

- `manifest.json` pins the external Drive export and extraction method.
- `cases.json` separates source, interpretation, confirmed facts, and reviewed
  expected results.
- The 61,882,654-byte source ZIP is deliberately not stored in Git.

See `docs/phase2_readiness/WHATSAPP_FIXTURE_CONTRACT.md` for duplicate scope,
confidence semantics, human correction, attachment retry, and financial
verification rules.
