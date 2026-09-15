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

echo "==> Checkout Frappe SHA"
git -C apps/frappe fetch --tags origin
git -C apps/frappe checkout --force "${FRAPPE_SHA}"

if [[ ! -d apps/erpnext ]]; then
  echo "==> get-app erpnext"
  bench get-app https://github.com/frappe/erpnext --branch version-15 || \
    bench get-app erpnext https://github.com/frappe/erpnext --branch version-15
fi
git -C apps/erpnext fetch --tags origin
git -C apps/erpnext checkout --force "${ERPNEXT_SHA}"

APP_SRC="${ROOT}/fresko_universe"
if [[ ! -d apps/fresko_universe ]]; then
  echo "==> Link fresko_universe from ${APP_SRC}"
  ln -sfn "${APP_SRC}" apps/fresko_universe
fi
if [[ -f sites/apps.txt ]] && ! grep -qx 'fresko_universe' sites/apps.txt 2>/dev/null; then
  echo fresko_universe >> sites/apps.txt
fi
bench setup requirements || true

mkdir -p sites
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
bench --site "${SITE}" install-app erpnext || true
echo "==> install-app fresko_universe"
bench --site "${SITE}" install-app fresko_universe
echo "==> migrate"
bench --site "${SITE}" migrate
echo "==> run-tests --app fresko_universe"
bench --site "${SITE}" run-tests --app fresko_universe
echo "==> CI bench OK"
