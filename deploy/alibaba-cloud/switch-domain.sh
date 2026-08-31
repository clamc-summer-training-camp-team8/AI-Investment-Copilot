#!/usr/bin/env bash
set -Eeuo pipefail

domain="${1:-}"
acme_email="${2:-}"
expected_ipv4="${3:-}"
deploy_dir="/opt/ai-investment-copilot/deploy"
env_file="$deploy_dir/.env.integration"

if [[ ! "$domain" =~ ^[A-Za-z0-9.-]+$ ]] \
  || [[ ! "$acme_email" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$ ]] \
  || [[ ! "$expected_ipv4" =~ ^[0-9.]+$ ]]; then
  echo "Usage: switch-domain.sh <domain> <acme-email> <expected-ipv4>" >&2
  exit 2
fi

resolved="$(getent ahostsv4 "$domain" | awk '{print $1}' | sort -u)"
if ! grep -Fxq "$expected_ipv4" <<<"$resolved"; then
  echo "域名 $domain 尚未解析到 $expected_ipv4；当前 A 记录: ${resolved:-无}" >&2
  exit 3
fi

test -s "$env_file"
backup="$env_file.before-domain-$(date -u +%Y%m%dT%H%M%SZ)"
cp -p "$env_file" "$backup"

set_env() {
  local key="$1" value="$2" temporary
  temporary="$(mktemp "$deploy_dir/.env.integration.XXXXXX")"
  awk -v key="$key" -v value="$value" '
    BEGIN { found=0 }
    index($0, key "=")==1 { print key "=" value; found=1; next }
    { print }
    END { if (!found) print key "=" value }
  ' "$env_file" > "$temporary"
  chmod 0600 "$temporary"
  mv "$temporary" "$env_file"
}

compose() {
  docker compose -f "$deploy_dir/docker-compose.integration.yml" \
    --env-file "$env_file" --env-file "$deploy_dir/release.env" "$@"
}

rollback() {
  status=$?
  cp -p "$backup" "$env_file"
  compose up -d --no-build --remove-orphans || true
  echo "域名切换失败，已恢复原配置: $backup" >&2
  exit "$status"
}
trap rollback ERR

set_env INTEGRATION_SITE_ADDRESS "$domain"
set_env INTEGRATION_TLS_ARGUMENT "$acme_email"
set_env CORS_ORIGINS "[\"https://$domain\"]"

compose config --quiet
compose up -d --no-build --remove-orphans

for attempt in $(seq 1 36); do
  if compose exec -T api python -c \
      "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3)" \
      >/dev/null 2>&1 \
    && curl --fail --silent --show-error --max-time 8 \
      "https://$domain/api/auth/config" >/dev/null; then
    trap - ERR
    echo "Domain ready: https://$domain/operations"
    echo "Previous configuration: $backup"
    exit 0
  fi
  sleep 5
done

compose logs --tail=160 gateway api
false
