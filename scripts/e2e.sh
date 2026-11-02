#!/usr/bin/env bash
# Builds the Compose stack under its own project name and ports, then runs the Playwright
# journey three times in a row with no retries (AC-24). Any failure stops it.
#   scripts/e2e.sh                     Playwright from frontend/node_modules (npx playwright install chromium)
#   E2E_RUNNER=container scripts/e2e.sh   Playwright in its pinned image, on the host network (CI, Linux)
#   E2E_KEEP=1 scripts/e2e.sh          leave the stack running afterwards
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
project=intakefold-e2e
playwright_image="mcr.microsoft.com/playwright:v1.64.1-noble@sha256:2f05f8a734509a7b3f26a912639488ee08f58a7b292d14d62271bcff9038768f"

# Apart from a demo stack on the default ports and network, so both can run at once.
export WEB_HOST_PORT="${E2E_WEB_PORT:-8280}"
export SINK_HOST_PORT="${E2E_SINK_PORT:-8290}"
export POSTGRES_HOST_PORT="${E2E_DB_PORT:-5481}"
export NETWORK_PREFIX="${E2E_NETWORK_PREFIX:-172.31.81}"
export WEB_ORIGINS="http://127.0.0.1:$WEB_HOST_PORT"
export E2E_BASE_URL="http://127.0.0.1:$WEB_HOST_PORT"

# An empty env file, so a developer's .env never changes what the journey runs against.
env_file="$(mktemp)"
compose() { docker compose -p "$project" --env-file "$env_file" -f "$root/compose.yaml" "$@"; }
sql() { compose exec -T db sh -c 'psql -qAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'; }

cleanup() {
  if [ "${E2E_KEEP:-}" != 1 ]; then
    compose down -v --remove-orphans >/dev/null 2>&1 || true
  fi
  rm -f "$env_file"
}
trap cleanup EXIT

compose up --build --detach --wait

echo "Waiting for the demo batch to be delivered..."
for _ in $(seq 1 60); do
  delivered="$(echo "SELECT count(*) FROM webhook_deliveries WHERE status = 'delivered';" | sql)"
  [ "$delivered" -gt 0 ] && break
  sleep 1
done
[ "$delivered" -gt 0 ] || { echo "No delivery reached the sink." >&2; exit 1; }

# One delivered webhook made to look as an outage leaves it: the job and the delivery dead.
# The journey requeues it, and the sender sends it again.
kill_one_delivery() {
  sql <<'SQL'
WITH target AS (
  SELECT jobs.id AS job_id, webhook_deliveries.id AS delivery_id
  FROM jobs
  JOIN webhook_deliveries ON jobs.payload ->> 'delivery_id' = webhook_deliveries.id::text
  WHERE jobs.kind = 'deliver_webhook' AND jobs.status = 'succeeded'
  ORDER BY jobs.created_at
  LIMIT 1
), dead_job AS (
  UPDATE jobs SET status = 'dead', attempts = max_attempts, last_error = 'DeliveryFailed'
  FROM target WHERE jobs.id = target.job_id
  RETURNING jobs.id
)
UPDATE webhook_deliveries SET status = 'dead'
FROM target WHERE webhook_deliveries.id = target.delivery_id
RETURNING (SELECT count(*) FROM dead_job);
SQL
}

run_journey() {
  if [ "${E2E_RUNNER:-}" = container ]; then
    # Git Bash on Windows would otherwise rewrite /work as a Windows path.
    MSYS_NO_PATHCONV=1 docker run --rm --network host --ipc host -e E2E_BASE_URL -e CI -e NPM_CONFIG_UPDATE_NOTIFIER=false \
      -v "$root/frontend:/work" -w /work "$playwright_image" npx playwright test
  else
    (cd "$root/frontend" && npx playwright test)
  fi
}

for run in 1 2 3; do
  echo "Journey run $run of 3"
  [ "$(kill_one_delivery)" = 1 ] || { echo "No delivery to turn into a dead job." >&2; exit 1; }
  run_journey
done

echo "The journey passed three times in a row."
