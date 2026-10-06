#!/usr/bin/env bash
# Gate 2: fresh bench → pinned Frappe/ERPNext → install fresko_universe → migrate → tests.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIN_FILE="${ROOT}/.github/frappe-versions.json"
BENCH_DIR="${BENCH_DIR:-${HOME}/frappe-bench}"
SITE="${FRAPPE_SITE:-test.localhost}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_ROOT_PASSWORD="${DB_ROOT_PASSWORD:-root}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin}"
BASELINE_SHA="${FRESKO_PHASE1_SHA:-dbf6e2f57b8d250193d0db880ed3eb3bc9fbc8e3}"
UPGRADE_SITE="${FRESKO_UPGRADE_SITE:-upgrade.localhost}"

# This entry point vendors app code and rewrites bench-wide test configuration.
# Refuse existing operational sites before any install/configuration mutation.
python3 - "${BENCH_DIR}" <<'CHECK'
import json
from pathlib import Path
import sys
bench = Path(sys.argv[1])
if bench.is_symlink():
    raise SystemExit("CI bench must not be a symlink")
sites = bench / "sites"
if sites.is_symlink():
    raise SystemExit("CI sites directory must not be a symlink")
if sites.exists():
    for site in sites.iterdir():
        config = site / "site_config.json"
        if site.is_symlink() or config.is_symlink():
            raise SystemExit("CI bench contains a symlinked site")
        if config.is_file() and not json.loads(config.read_text()).get("fresko_disposable_browser_site"):
            raise SystemExit("CI bench contains an existing site without its disposable marker")
CHECK

if [[ ! -f "${PIN_FILE}" ]]; then
  echo "Missing pin file: ${PIN_FILE}" >&2
  exit 1
fi

eval "$(python3 -c "
import json
from pathlib import Path
pins = json.loads(Path(r'${PIN_FILE}').read_text())
print('export FRAPPE_SHA=' + pins['frappe']['sha'])
print('export ERPNEXT_SHA=' + pins['erpnext']['sha'])
print('export FRAPPE_TAG=' + pins['frappe']['tag'])
print('export ERPNEXT_TAG=' + pins['erpnext']['tag'])
")"

echo "==> Pins: Frappe ${FRAPPE_TAG} @ ${FRAPPE_SHA}"
echo "==> Pins: ERPNext ${ERPNEXT_TAG} @ ${ERPNEXT_SHA}"

if [[ ! -d "${BENCH_DIR}" ]]; then
  echo "==> bench init ${BENCH_DIR}"
  bench init "${BENCH_DIR}" \
    --frappe-path https://github.com/frappe/frappe \
    --frappe-branch version-15 \
    --python python3 \
    --skip-redis-config-generation \
    --skip-assets
fi

cd "${BENCH_DIR}"

# bench init / get-app often name the remote "upstream", not "origin", and use a shallow clone.
pin_checkout() {
  local app_dir="$1"
  local sha="$2"
  local tag="$3"
  local remote
  remote="$(git -C "${app_dir}" remote | head -n1)"
  if [[ -z "${remote}" ]]; then
    echo "No git remote in ${app_dir}" >&2
    exit 1
  fi
  echo "==> Checkout ${app_dir} @ ${tag} (${sha}) via remote ${remote}"
  # Shallow clone of version-15 tip will not contain the pin SHA — fetch it explicitly.
  git -C "${app_dir}" fetch --depth 1 "${remote}" "${sha}"
  git -C "${app_dir}" fetch --depth 1 "${remote}" "refs/tags/${tag}:refs/tags/${tag}" || true
  git -C "${app_dir}" checkout --force "${sha}"
  local got
  got="$(git -C "${app_dir}" rev-parse HEAD)"
  if [[ "${got}" != "${sha}" ]]; then
    echo "Pin mismatch in ${app_dir}: got ${got}, want ${sha}" >&2
    exit 1
  fi
}

echo "==> Checkout Frappe SHA"
pin_checkout apps/frappe "${FRAPPE_SHA}" "${FRAPPE_TAG}"
echo "==> Reinstall pinned frappe into bench env"
./env/bin/pip install -q -e ./apps/frappe

if [[ ! -d apps/erpnext ]]; then
  echo "==> get-app erpnext"
  bench get-app https://github.com/frappe/erpnext --branch version-15 --skip-assets || \
    bench get-app erpnext https://github.com/frappe/erpnext --branch version-15 --skip-assets
fi
pin_checkout apps/erpnext "${ERPNEXT_SHA}" "${ERPNEXT_TAG}"
echo "==> Reinstall pinned erpnext into bench env"
./env/bin/pip install -q -e ./apps/erpnext

mkdir -p sites
# Never register fresko_universe before it is copied + pip-installed (breaks new-site).
if [[ -f sites/apps.txt ]]; then
  grep -vx 'fresko_universe' sites/apps.txt > sites/apps.txt.tmp || true
  mv sites/apps.txt.tmp sites/apps.txt
fi

cat > sites/common_site_config.json <<JSON
{
  "db_host": "${DB_HOST}",
  "redis_cache": "redis://127.0.0.1:6379",
  "redis_queue": "redis://127.0.0.1:6379",
  "redis_socketio": "redis://127.0.0.1:6379",
  "developer_mode": 1
}
JSON

if [[ ! -d "sites/${SITE}" ]]; then
  echo "==> new-site ${SITE}"
  bench new-site "${SITE}" \
    --mariadb-root-password "${DB_ROOT_PASSWORD}" \
    --admin-password "${ADMIN_PASSWORD}" \
    --no-mariadb-socket \
    --db-host "${DB_HOST}" \
    --set-default
  bench --site "${SITE}" set-config fresko_disposable_browser_site true
fi

echo "==> install-app erpnext"
if ! bench --site "${SITE}" list-apps 2>/dev/null | grep -q '^erpnext'; then
  bench --site "${SITE}" install-app erpnext
fi

vendor_fresko_app() {
  local app_src="$1"
  local label="$2"
  echo "==> Vendor fresko_universe ${label} from ${app_src}"
  rm -rf apps/fresko_universe
  mkdir -p apps/fresko_universe
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete --exclude '.git' --exclude '*.egg-info' --exclude '__pycache__' \
      "${app_src}/" apps/fresko_universe/
  else
    cp -a "${app_src}/." apps/fresko_universe/
    rm -rf apps/fresko_universe/.git apps/fresko_universe/*.egg-info
  fi
  git -C apps/fresko_universe init -q
  git -C apps/fresko_universe config user.email "ci@fresko.local"
  git -C apps/fresko_universe config user.name "Fresko CI"
  git -C apps/fresko_universe add -A
  git -C apps/fresko_universe commit -qm "ci: vendor fresko_universe ${label}"
  ./env/bin/pip install -q -e ./apps/fresko_universe
}

# Exercise the same normal app-root Git install boundary used by private benches.
EXPORT_TMP="$(mktemp -d)"
trap 'rm -rf "${EXPORT_TMP}"' EXIT
FRESKO_SOURCE_SHA="$(git -C "${ROOT}" rev-parse HEAD)"
python3 "${ROOT}/scripts/export_deployment_app.py" --repo "${ROOT}" --commit "${FRESKO_SOURCE_SHA}" --output "${EXPORT_TMP}/fresko_universe"
APP_SRC="${EXPORT_TMP}/fresko_universe"
git -C "${APP_SRC}" init -q
git -C "${APP_SRC}" config user.email "ci@fresko.local"
git -C "${APP_SRC}" config user.name "Fresko CI"
git -C "${APP_SRC}" add -A
git -C "${APP_SRC}" commit -qm "Deployment export ${FRESKO_SOURCE_SHA}"
bench get-app --skip-assets "file://${APP_SRC}"

# Register after pip install (must not be present during new-site).
mkdir -p sites
touch sites/apps.txt
if ! grep -qx 'fresko_universe' sites/apps.txt; then
  echo fresko_universe >> sites/apps.txt
fi

echo "==> install-app fresko_universe"
if ! bench --site "${SITE}" list-apps 2>/dev/null | grep -q '^fresko_universe'; then
  bench --site "${SITE}" install-app fresko_universe
fi

echo "==> migrate"
bench --site "${SITE}" migrate

# run-tests --app fresko_universe only runs fresko before_tests hooks (none yet).
# ERPNext/Frappe masters (Gender, Warehouse Type Transit, Company, …) come from
# erpnext.setup.utils.before_tests → setup_complete. Invoke it explicitly.
echo "==> allow_tests + ERPNext before_tests bootstrap (setup wizard + company)"
bench --site "${SITE}" set-config allow_tests true
bench --site "${SITE}" execute erpnext.setup.utils.before_tests
echo "==> ERPNext before_tests finished"

echo "==> run-tests --app fresko_universe"
# Pinned Frappe only propagates unittest failures to exit status when CI is set.
CI=1 bench --site "${SITE}" run-tests --app fresko_universe

echo "==> prove exact Phase 1-to-current schema migrations (registered seeded proofs)"
MIGRATION_HARNESS="${ROOT}/scripts/run_schema_migration_harness.py"
python3 "${MIGRATION_HARNESS}" --validate-only
if ! git -C "${ROOT}" merge-base --is-ancestor "${BASELINE_SHA}" HEAD; then
  echo "Phase 1 baseline ${BASELINE_SHA} is not available as an ancestor of HEAD" >&2
  exit 1
fi

UPGRADE_TMP="$(mktemp -d)"
trap 'rm -rf "${UPGRADE_TMP}" "${EXPORT_TMP}"' EXIT
git -C "${ROOT}" archive "${BASELINE_SHA}" fresko_universe | tar -x -C "${UPGRADE_TMP}"
vendor_fresko_app "${UPGRADE_TMP}/fresko_universe" "phase1-${BASELINE_SHA}"

if [[ -d "sites/${UPGRADE_SITE}" ]]; then
  echo "Upgrade proof site already exists: ${UPGRADE_SITE}" >&2
  exit 1
fi
bench new-site "${UPGRADE_SITE}" \
  --mariadb-root-password "${DB_ROOT_PASSWORD}" \
  --admin-password "${ADMIN_PASSWORD}" \
  --no-mariadb-socket \
  --db-host "${DB_HOST}"
bench --site "${UPGRADE_SITE}" install-app erpnext
bench --site "${UPGRADE_SITE}" install-app fresko_universe
./env/bin/python "${MIGRATION_HARNESS}" --site "${UPGRADE_SITE}" seed_phase1

vendor_fresko_app "${APP_SRC}" "current-upgrade-candidate"
diff -qr \
  --exclude='.git' \
  --exclude='*.egg-info' \
  --exclude='__pycache__' \
  "${APP_SRC}" apps/fresko_universe

bench --site "${UPGRADE_SITE}" migrate
./env/bin/python "${MIGRATION_HARNESS}" --site "${UPGRADE_SITE}" verify_first_migrate
bench --site "${UPGRADE_SITE}" migrate
./env/bin/python "${MIGRATION_HARNESS}" --site "${UPGRADE_SITE}" verify_second_migrate

# Independently exercise the exact merged pre-commercial baseline. The older
# registered Phase 1 proof remains intact; it cannot substitute for this path.
COMMERCIAL_BASELINE_SHA="579a8465f363105eb6e78c15cb173156e2c0df93"
COMMERCIAL_UPGRADE_SITE="commercial-upgrade.localhost"
COMMERCIAL_PROOF="${ROOT}/scripts/prove_commercial_sale_upgrade.py"
git -C "${ROOT}" merge-base --is-ancestor "${COMMERCIAL_BASELINE_SHA}" HEAD
mkdir -p "${UPGRADE_TMP}/commercial-main"
git -C "${ROOT}" archive "${COMMERCIAL_BASELINE_SHA}" fresko_universe | tar -x -C "${UPGRADE_TMP}/commercial-main"
vendor_fresko_app "${UPGRADE_TMP}/commercial-main/fresko_universe" "commercial-main-${COMMERCIAL_BASELINE_SHA}"
if [[ -d "sites/${COMMERCIAL_UPGRADE_SITE}" ]]; then
  echo "Commercial upgrade proof site already exists: ${COMMERCIAL_UPGRADE_SITE}" >&2
  exit 1
fi
bench new-site "${COMMERCIAL_UPGRADE_SITE}" \
  --mariadb-root-password "${DB_ROOT_PASSWORD}" \
  --admin-password "${ADMIN_PASSWORD}" \
  --no-mariadb-socket --db-host "${DB_HOST}"
bench --site "${COMMERCIAL_UPGRADE_SITE}" install-app erpnext
bench --site "${COMMERCIAL_UPGRADE_SITE}" install-app fresko_universe
./env/bin/python "${COMMERCIAL_PROOF}" --site "${COMMERCIAL_UPGRADE_SITE}" seed_current_main
vendor_fresko_app "${APP_SRC}" "commercial-upgrade-candidate"
diff -qr --exclude='.git' --exclude='*.egg-info' --exclude='__pycache__' "${APP_SRC}" apps/fresko_universe
bench --site "${COMMERCIAL_UPGRADE_SITE}" migrate
./env/bin/python "${COMMERCIAL_PROOF}" --site "${COMMERCIAL_UPGRADE_SITE}" verify_first_migrate
bench --site "${COMMERCIAL_UPGRADE_SITE}" migrate
./env/bin/python "${COMMERCIAL_PROOF}" --site "${COMMERCIAL_UPGRADE_SITE}" verify_second_migrate

# Upgrade the exact merged commercial baseline separately for money-ledger
# preservation. Synthetic baseline values are migration sentinels only.
MONEY_BASELINE_SHA="b140b800b021c4317931e37a723a140740b2fc4c"
MONEY_UPGRADE_SITE="money-upgrade.localhost"
MONEY_PROOF="${ROOT}/scripts/prove_money_upgrade.py"
git -C "${ROOT}" merge-base --is-ancestor "${MONEY_BASELINE_SHA}" HEAD
mkdir -p "${UPGRADE_TMP}/money-main"
git -C "${ROOT}" archive "${MONEY_BASELINE_SHA}" fresko_universe | tar -x -C "${UPGRADE_TMP}/money-main"
vendor_fresko_app "${UPGRADE_TMP}/money-main/fresko_universe" "money-main-${MONEY_BASELINE_SHA}"
if [[ -d "sites/${MONEY_UPGRADE_SITE}" ]]; then
  echo "Money upgrade proof site already exists: ${MONEY_UPGRADE_SITE}" >&2
  exit 1
fi
bench new-site "${MONEY_UPGRADE_SITE}" \
  --mariadb-root-password "${DB_ROOT_PASSWORD}" \
  --admin-password "${ADMIN_PASSWORD}" \
  --no-mariadb-socket --db-host "${DB_HOST}"
bench --site "${MONEY_UPGRADE_SITE}" install-app erpnext
bench --site "${MONEY_UPGRADE_SITE}" install-app fresko_universe
./env/bin/python "${MONEY_PROOF}" --site "${MONEY_UPGRADE_SITE}" seed_current_main
vendor_fresko_app "${APP_SRC}" "money-upgrade-candidate"
diff -qr --exclude='.git' --exclude='*.egg-info' --exclude='__pycache__' "${APP_SRC}" apps/fresko_universe
bench --site "${MONEY_UPGRADE_SITE}" migrate
./env/bin/python "${MONEY_PROOF}" --site "${MONEY_UPGRADE_SITE}" verify_first_migrate
bench --site "${MONEY_UPGRADE_SITE}" migrate
./env/bin/python "${MONEY_PROOF}" --site "${MONEY_UPGRADE_SITE}" verify_second_migrate

echo "==> CI bench OK"
