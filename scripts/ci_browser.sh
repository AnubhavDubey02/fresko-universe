#!/usr/bin/env bash
# Temporary CI Frappe browser site; never a production/staging deployment recipe.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH_DIR="${BENCH_DIR:?Pinned bench required}"
SITE="${FRAPPE_SITE:-test.localhost}"
: "${FRESKO_BROWSER_MANIFEST:?Private manifest path required}"
: "${FRESKO_BROWSER_ARTIFACTS:?Sanitized artifact path required}"
: "${FRESKO_BROWSER_URL:?Browser origin required}"
python3 - <<'CHECK'
import json,os
from pathlib import Path
from urllib.parse import urlparse
origin=urlparse(os.environ["FRESKO_BROWSER_URL"])
if origin.scheme != "http" or origin.hostname not in ("127.0.0.1", "localhost") or origin.port != 8000 or origin.username or origin.password or origin.path not in ("", "/"):
    raise SystemExit("CI browser runner only accepts loopback port 8000")
site=os.environ.get("FRAPPE_SITE", "test.localhost")
config=json.loads((Path(os.environ["BENCH_DIR"])/"sites"/site/"site_config.json").read_text())
if not config.get("fresko_disposable_browser_site") or not config.get("allow_tests"):
    raise SystemExit("Pre-existing disposable-site marker and allow_tests required")
manifest=Path(os.environ["FRESKO_BROWSER_MANIFEST"]).resolve()
artifacts=Path(os.environ["FRESKO_BROWSER_ARTIFACTS"]).resolve()
if manifest.exists() or manifest.is_relative_to(artifacts):
    raise SystemExit("Credential manifest must be new and outside public artifacts")
manifest.parent.mkdir(parents=True,exist_ok=True)
manifest.parent.chmod(0o700)
CHECK
WEB_PID=""
SOCKET_PID=""
trap 'if [[ -n "${WEB_PID}" ]]; then kill "${WEB_PID}" 2>/dev/null || true; fi; if [[ -n "${SOCKET_PID}" ]]; then kill "${SOCKET_PID}" 2>/dev/null || true; fi; rm -f "${FRESKO_BROWSER_MANIFEST}"' EXIT
cd "${BENCH_DIR}"
bench --site "${SITE}" set-config fresko_browser_fixture_only true
bench --site "${SITE}" execute fresko_universe.tests.browser_fixture.seed --kwargs "$(python3 -c 'import json,os;print(json.dumps({"manifest_path":os.environ["FRESKO_BROWSER_MANIFEST"]}))')"
bench setup requirements --node
bench build --apps frappe,erpnext,fresko_universe
./env/bin/pip install -r "${ROOT}/scripts/browser-requirements.txt"
./env/bin/python -m playwright install --with-deps chromium
bench set-config -g socketio_port 9000
node apps/frappe/socketio.js > "${BENCH_DIR}/logs/browser-socketio.log" 2>&1 &
SOCKET_PID=$!
DEV_SERVER=1 bench --site "${SITE}" serve --port 8000 --noreload > "${BENCH_DIR}/logs/browser-web.log" 2>&1 &
WEB_PID=$!
for attempt in $(seq 1 60); do
  if curl --silent --fail "${FRESKO_BROWSER_URL}/login" > /dev/null; then break; fi
  sleep 1
done
./env/bin/python "${ROOT}/scripts/browser_acceptance.py" --manifest "${FRESKO_BROWSER_MANIFEST}" --url "${FRESKO_BROWSER_URL}" --artifacts "${FRESKO_BROWSER_ARTIFACTS}"
./env/bin/python "${ROOT}/scripts/browser_recovery.py" --bench "${BENCH_DIR}" --site "${SITE}" --manifest "${FRESKO_BROWSER_MANIFEST}" --output "${FRESKO_BROWSER_ARTIFACTS}/recovery.json"
