# Sources — Fresko Universe Phase 0+1

## Google Drive (operational originals)

| Label | Drive file id | Title | Phase use |
|---|---|---|---|
| Final Ledger | `1VStDqHArIrFDbOVdGZCWlQSlwmctv47q` | Fresko Third Container - Final Ledger - 3196 Crates - 09 Sep 2026.xlsx | Phase 1 reference (lots / sold qty / rates) |
| Collection Set | `1t781voiiSzd0puxQzg0bBTR3j8SoJVdD` | Fresko Third Container - Collection Set - 07 Sep 2026.xlsx | Phase 1 reference (buyer/collection) |
| Control Set | `14I4Q_oiMbGzd84T7iow83NqTzCUkw_ht` | Fresko Third Container - Internal Digital Control Set - 07 Sep 2026.xlsx | Phase 1 reference (control totals) |
| WhatsApp zip (14-Sep historical export) | `12atetNKpUENkmhUeTj1DquEPQK2X2ID9` | WhatsApp Chat - FRESKO UNIVERSAL BACKEND TEAM.zip (~42 MB) | Historical source; no live ingestion |
| WhatsApp zip (18-Sep readiness source) | `1JYTZvKROdcy2tRMbbgfiRaVb7qZ4drxS` | WhatsApp Chat - FRESKO UNIVERSAL BACKEND TEAM.zip (61,882,654 bytes) | Phase 1 closeout / Phase 2 readiness fixtures only; no live ingestion |

Drive folder parent (xlsx): `0AGdgZm7J1lvQUk9PVA`

### 18-Sep WhatsApp export integrity

- Drive ID: `1JYTZvKROdcy2tRMbbgfiRaVb7qZ4drxS`
- Filename: `WhatsApp Chat - FRESKO UNIVERSAL BACKEND TEAM.zip`
- Drive size: `61,882,654` bytes
- Locally verified SHA-256:
  `d2ea3162c657b90dcf346b18609f883e27eb6a9640ab8cc7fc47772b602c2b02`
- Extraction: connected Drive raw-file fetch with inline base64 disabled,
  authenticated streamed download to `/tmp`, `unzip -t` integrity check, then
  transcript-only extraction with `unzip -p ... _chat.txt`. Representative XLSX
  and PDF members were read directly from the ZIP for fixture review.
- Archive inventory: 139 entries; `_chat.txt` covers 2-Sep through 18-Sep-2026.
- Storage rule: the full ZIP remains outside Git. Only compact reviewed fixture
  records and provenance are committed.

## Staged fixtures in-repo

Under `fresko_universe/fresko_universe/fixtures/drive/`:

| File | Purpose |
|---|---|
| `SAMPLE_lots_buyers_rates.xlsx` | Anonymized sample lots, count-size rate bands, buyer alias proposals for unit/integration fixtures |
| `SAMPLE_container_header.xlsx` | Minimal container header (3196 crates shape) |
| `README.md` | Fixture notes |

Full Drive xlsx binaries are **not** committed (keep repo light; pull from Drive when needed for offline QA). Sample workbooks mirror the column shapes used by Phase 1 rate/lot/buyer tests.

## Spec docs (authoritative for Phase 1)

- `docs/PHASE1_BLUEPRINT_FINAL.md`
- `docs/DECISIONS.md` (D1, D3, D4, D5, D6, D10 locked)
- `docs/OPEN_QUESTIONS.md`
- `docs/DOCTYPE_CONTAINER_DEAL_v1.md` (superseded where it conflicts with blueprint + locked decisions — especially D4)
