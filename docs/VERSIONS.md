# VERSIONS — pinned Frappe / ERPNext (Gate 2)

Pinned for reproducible CI / Docker bench. Do not float to `version-15` without updating this file and verifying migrate + tests.

| Component | Tag | Commit SHA |
|---|---|---|
| **Frappe** | `v15.120.1` | `9f8ae9cd25b6735be345da6cc12e9f5a96050c68` |
| **ERPNext** | `v15.121.2` | `df8b7f9648c2ec4da12db8c4022edc8dd1018c6b` |

## Notes

- Matched Sep-2026 v15 pair (Anubhav Gate 2).
- Install via bench: `bench get-app frappe --branch v15.120.1` then checkout SHA; same for ERPNext `v15.121.2`.
- CI: `.github/workflows/frappe-bench.yml` and/or `docker-compose.bench.yml` + `scripts/ci_bench.sh`.
- App under test: `fresko_universe` from this repository checkout.

## Verify pins

```bash
# Optional: confirm tags still point at recorded SHAs
git ls-remote --tags https://github.com/frappe/frappe.git 'v15.120.1*'
git ls-remote --tags https://github.com/frappe/erpnext.git 'v15.121.2*'
```
