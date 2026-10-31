#!/usr/bin/env bash
# Runs everything CI runs. Any failure stops the script, so it can guard a push.
#   scripts/check.sh            all checks
#   scripts/check.sh backend    one group: backend, frontend or repository
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
group="${1:-all}"

backend() {
  cd "$root/backend"
  uv sync --locked
  uv run ruff format --check .
  uv run ruff check .
  uv run pyright
  uv run pytest

  local requirements
  requirements="$(mktemp)"
  uv export --locked --no-emit-project --format requirements-txt --output-file "$requirements" >/dev/null
  uv run pip-audit --requirement "$requirements" --require-hashes --disable-pip
  rm -f "$requirements"
}

frontend() {
  cd "$root/frontend"
  npm ci
  npm run lint
  npm run format:check
  npm run typecheck
  npm test
  npm run build
  # Stricter for what ships than for dev tooling. See "Known issues" in PROGRESS.md.
  npm audit --omit=dev --audit-level=moderate
  npm audit --audit-level=high
}

repository() {
  cd "$root"
  bash scripts/install-tools.sh
  .tools/gitleaks git --redact --no-banner .
  .tools/actionlint
  git ls-files -z | xargs -0 .tools/ec
}

case "$group" in
  all)
    (backend)
    (frontend)
    (repository)
    ;;
  backend | frontend | repository) ("$group") ;;
  *)
    echo "Unknown group: $group" >&2
    exit 2
    ;;
esac

echo "All $group checks passed."
