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

## 25-Sep real-data validation pack

The reviewed archive and operational workbook binaries remain outside Git. The
sanitized acceptance manifest is
`fresko_universe/fresko_universe/fixtures/real_data_shadow/manifest.json`.

- Archive SHA-256:
  `E875335141BE021DA1B0315A7046D6798E638CA5F8DE4F89BAB607404BACC78F`.
- `Fresko_Plum_Official_Outward_Update_21_Sep_2026.xlsx` SHA-256:
  `3B9D5D33BF8425819A88AFDCD9B07329A4C66F48A565D09719C663EA651A0BFF`.
- `Fresko_Grapes_Official_Outward_Update_21_Sep_2026.xlsx` SHA-256:
  `71994E54F585DDC56C07EF76825F8B60739BAC086D367654750A6B0A1486536B`.
- `Fresko_Universal_CA_Master_Accounting_Reconciliation_25_Sep_2026_AUDITED.xlsx`
  SHA-256:
  `54FB00CE898373E84F1463E78B32E05B801A5C3D70C415668474A916BE268F68`.
- Exact sheet/range references and expected cut-off totals live in the sanitized
  manifest and are validated by `scripts/validate_real_data_shadow_fixture.py`.
- The exact Sohail handwritten photo for 92 at INR 700 is **not yet linked or
  hash-verified**. The fixture therefore records a pending photo source and must
  reject activation; it does not pretend that this case is evidenced by the CA
  workbook.

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
