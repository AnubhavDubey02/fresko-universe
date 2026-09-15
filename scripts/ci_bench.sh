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
fi

echo "==> install-app erpnext"
if ! bench --site "${SITE}" list-apps 2>/dev/null | grep -q '^erpnext'; then
  bench --site "${SITE}" install-app erpnext
fi

APP_SRC="${ROOT}/fresko_universe"
echo "==> Vendor fresko_universe from ${APP_SRC} (copy + mini git repo for bench)"
rm -rf apps/fresko_universe
mkdir -p apps/fresko_universe
# Prefer rsync; fall back to cp
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete --exclude '.git' --exclude '*.egg-info' --exclude '__pycache__' \
    "${APP_SRC}/" apps/fresko_universe/
else
  cp -a "${APP_SRC}/." apps/fresko_universe/
  rm -rf apps/fresko_universe/.git apps/fresko_universe/*.egg-info
fi
git -C apps/fresko_universe init -q
git -C apps/fresko_universe config user.email "ci@fresko.local"
git -C apps/fresko_universe config user.name "Fresko CI"
git -C apps/fresko_universe add -A
git -C apps/fresko_universe commit -qm "ci: vendor fresko_universe for Gate 2 bench"

echo "==> pip install -e fresko_universe"
./env/bin/pip install -q -e ./apps/fresko_universe

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
# Fail-closed sanity on the two masters that already bit us.
for pair in "Warehouse Type|Transit" "Gender|Female"; do
  DT="${pair%%|*}"; NAME="${pair##*|}"
  exists="$(bench --site "${SITE}" execute frappe.db.exists --args "['${DT}', '${NAME}']" | tr -d '[:space:]')"
  if [[ "${exists}" != "True" && "${exists}" != "1" ]]; then
    echo "ERROR: missing ${DT}: ${NAME} after erpnext.before_tests (got: ${exists})" >&2
    exit 1
  fi
done
echo "==> ERPNext test masters present (Transit, Gender Female)"

echo "==> run-tests --app fresko_universe"
bench --site "${SITE}" run-tests --app fresko_universe

echo "==> CI bench OK"
