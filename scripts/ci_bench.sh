#!/usr/bin/env bash
# Gate 2: reproducible bench migrate + fresko_universe tests.
# Pins from docs/VERSIONS.md — Frappe v15.120.1 / ERPNext v15.121.2
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRAPPE_TAG="${FRAPPE_TAG:-v15.120.1}"
FRAPPE_SHA="${FRAPPE_SHA:-9f8ae9cd25b6735be345da6cc12e9f5a96050c68}"
ERPNEXT_TAG="${ERPNEXT_TAG:-v15.121.2}"
ERPNEXT_SHA="${ERPNEXT_SHA:-df8b7f9648c2ec4da12db8c4022edc8dd1018c6b}"
BENCH_DIR="${BENCH_DIR:-$ROOT/.bench/frappe-bench}"
SITE="${SITE:-test.localhost}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-3307}"
MYSQL_ROOT_PASSWORD="${MYSQL_ROOT_PASSWORD:-root}"

echo "==> Gate 2 CI bench"
echo "    Frappe  $FRAPPE_TAG @ $FRAPPE_SHA"
echo "    ERPNext $ERPNEXT_TAG @ $ERPNEXT_SHA"

# Always run smoke unit first (no bench required)
echo "==> Smoke unit tests"
( cd "$ROOT/fresko_universe" && python3 -m unittest tests.test_smoke_unit -v )

# Start MariaDB + Redis if docker available
if command -v docker >/dev/null 2>&1; then
  echo "==> Starting docker-compose.bench.yml services"
  docker compose -f "$ROOT/docker-compose.bench.yml" up -d
  echo "==> Waiting for MariaDB"
  for i in $(seq 1 60); do
    if docker compose -f "$ROOT/docker-compose.bench.yml" exec -T mariadb \
        mysqladmin ping -uroot -proot --silent 2>/dev/null; then
      break
    fi
    sleep 2
  done
else
  echo "WARN: docker not found — assuming MariaDB/Redis already on $DB_HOST:$DB_PORT"
fi

if ! command -v bench >/dev/null 2>&1; then
  echo "==> Installing frappe-bench CLI"
  pip install --upgrade pip
  pip install 'frappe-bench==5.22.9'
fi

mkdir -p "$(dirname "$BENCH_DIR")"
if [[ ! -d "$BENCH_DIR" ]]; then
  echo "==> bench init"
  bench init --frappe-branch "$FRAPPE_TAG" --skip-redis-config-generation --skip-assets "$BENCH_DIR"
fi

cd "$BENCH_DIR"
git -C apps/frappe fetch --tags origin || true
git -C apps/frappe checkout "$FRAPPE_SHA"
./env/bin/pip install -e apps/frappe

if [[ ! -d apps/erpnext ]]; then
  bench get-app erpnext --branch "$ERPNEXT_TAG"
fi
git -C apps/erpnext fetch --tags origin || true
git -C apps/erpnext checkout "$ERPNEXT_SHA"
./env/bin/pip install -e apps/erpnext

bench set-config -g db_host "$DB_HOST"
# MariaDB may be on non-default port via compose
export MYSQL_HOST="$DB_HOST"
bench set-config -g redis_cache "redis://127.0.0.1:6379"
bench set-config -g redis_queue "redis://127.0.0.1:6380"
bench set-config -g redis_socketio "redis://127.0.0.1:6379"

if [[ ! -d "sites/$SITE" ]]; then
  # Force TCP port when using compose-mapped 3307
  if [[ "$DB_PORT" != "3306" ]]; then
    export BENCH_MYSQL_PORT="$DB_PORT"
  fi
  bench new-site "$SITE" \
    --mariadb-root-password "$MYSQL_ROOT_PASSWORD" \
    --admin-password admin \
    --no-mariadb-socket \
    --db-host "$DB_HOST" \
    --db-port "$DB_PORT" \
    --db-root-username root || true
  # Fallback without --db-port if older bench
  if [[ ! -d "sites/$SITE" ]]; then
    bench new-site "$SITE" \
      --mariadb-root-password "$MYSQL_ROOT_PASSWORD" \
      --admin-password admin \
      --no-mariadb-socket \
      --db-root-username root
  fi
  bench --site "$SITE" install-app erpnext
fi

# Link fresko_universe from repo checkout
rm -rf apps/fresko_universe
ln -sfn "$ROOT/fresko_universe" apps/fresko_universe
./env/bin/pip install -e apps/fresko_universe
bench --site "$SITE" install-app fresko_universe || true

echo "==> migrate"
bench --site "$SITE" migrate

echo "==> run-tests --app fresko_universe"
bench --site "$SITE" run-tests --app fresko_universe

echo "==> Gate 2 PASS"
