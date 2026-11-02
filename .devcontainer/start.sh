#!/usr/bin/env bash
# Starts the demo stack inside the dev container, on every start of the container.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Codespaces serves a forwarded port at its own https address. The API accepts unsafe requests
# only from listed origins, and over https the session cookie can stay Secure.
if [ -n "${CODESPACE_NAME:-}" ] && [ -n "${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-}" ]; then
  export WEB_ORIGINS="https://${CODESPACE_NAME}-8180.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}"
  export WEB_INSECURE_COOKIES=false
fi

docker compose up --build --detach --wait
echo "Intakefold is running on port 8180. The demo accounts are on the sign-in page."
