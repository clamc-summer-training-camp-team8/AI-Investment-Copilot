#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 root 或 sudo 执行本脚本。" >&2
  exit 2
fi

stage_dir="${1:-}"
deploy_user="${DEPLOY_USER:-root}"
deploy_root="/opt/ai-investment-copilot"
deploy_dir="$deploy_root/deploy"

if [[ -z "$stage_dir" || ! -d "$stage_dir" ]]; then
  echo "Usage: install-release.sh </tmp/ai-copilot-release-* directory>" >&2
  exit 2
fi
stage_real="$(realpath "$stage_dir")"
case "$stage_real" in
  /tmp/ai-copilot-release-*) ;;
  *) echo "发布暂存目录必须位于 /tmp/ai-copilot-release-*。" >&2; exit 2 ;;
esac
if ! id "$deploy_user" >/dev/null 2>&1; then
  echo "部署用户不存在: $deploy_user" >&2
  exit 2
fi

required=(
  docker-compose.integration.yml
  Caddyfile
  backup.sh
  restore-drill.sh
  release.env
)
for file in "${required[@]}"; do
  test -s "$stage_real/$file" || { echo "发布包缺少 $file" >&2; exit 2; }
done

app_image="$(sed -n 's/^APP_IMAGE=//p' "$stage_real/release.env")"
web_image="$(sed -n 's/^WEB_IMAGE=//p' "$stage_real/release.env")"
if [[ ! "$app_image" =~ ^ai-investment-copilot-app:[A-Za-z0-9_.-]+$ ]] \
  || [[ ! "$web_image" =~ ^ai-investment-copilot-web:[A-Za-z0-9_.-]+$ ]]; then
  echo "release.env 中的镜像标签不合法。" >&2
  exit 2
fi

install -d -m 0750 -o "$deploy_user" -g "$deploy_user" "$deploy_dir/integration"
install -m 0644 "$stage_real/docker-compose.integration.yml" \
  "$deploy_dir/docker-compose.integration.yml"
install -m 0644 "$stage_real/Caddyfile" "$deploy_dir/integration/Caddyfile"
install -m 0750 "$stage_real/backup.sh" "$deploy_dir/integration/backup.sh"
install -m 0750 "$stage_real/restore-drill.sh" "$deploy_dir/integration/restore-drill.sh"

if [[ ! -s "$deploy_dir/.env.integration" ]]; then
  test -s "$stage_real/.env.integration" || {
    echo "首次发布需要 .env.integration。" >&2
    exit 2
  }
  install -m 0600 "$stage_real/.env.integration" "$deploy_dir/.env.integration"
else
  echo "保留服务器现有 .env.integration，不自动轮换持久化服务密钥。"
fi

if ! grep -q '^AUTH_JWT_SECRET=' "$deploy_dir/.env.integration"; then
  test -s "$stage_real/auth-jwt-secret" || {
    echo "现有环境缺少 AUTH_JWT_SECRET，且发布包未提供迁移密钥。" >&2
    exit 2
  }
  printf '\nAUTH_JWT_SECRET=%s\n' "$(tr -d '\r\n' < "$stage_real/auth-jwt-secret")" \
    >> "$deploy_dir/.env.integration"
fi

if [[ -s "$stage_real/images.tar.gz" ]]; then
  docker load --input "$stage_real/images.tar.gz"
else
  docker image inspect "$app_image" "$web_image" >/dev/null
fi

cd "$deploy_dir"
if [[ -s release.env ]]; then
  cp -p release.env release.env.previous
fi
install -m 0600 "$stage_real/release.env" release.env.next
mv release.env.next release.env

compose() {
  docker compose -f docker-compose.integration.yml \
    --env-file .env.integration --env-file release.env "$@"
}

rollback() {
  status=$?
  echo "发布失败，保留日志并尝试恢复上一镜像版本。" >&2
  if [[ -s release.env.previous ]]; then
    mv release.env.previous release.env
    compose up -d --no-build --remove-orphans || true
  fi
  exit "$status"
}
trap rollback ERR

compose config --quiet
compose up -d --no-build --remove-orphans
for attempt in $(seq 1 72); do
  if compose exec -T api python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3)" \
    >/dev/null 2>&1; then
    if [[ -s "$stage_real/bootstrap-user" ]]; then
      initial_user="$(sed -n '1p' "$stage_real/bootstrap-user")"
      initial_password="$(sed -n '2p' "$stage_real/bootstrap-user")"
      printf '%s' "$initial_password" | compose exec -T api \
        python -m scripts.manage_user --user "$initial_user" --password-stdin \
        --teams research,investment,security-admin --admin
    fi
    trap - ERR
    compose ps
    docker image prune --force --filter 'until=168h' >/dev/null
    rm -f \
      "$stage_real/images.tar.gz" \
      "$stage_real/docker-compose.integration.yml" \
      "$stage_real/Caddyfile" \
      "$stage_real/backup.sh" \
      "$stage_real/restore-drill.sh" \
      "$stage_real/release.env" \
      "$stage_real/.env.integration" \
      "$stage_real/auth-jwt-secret" \
      "$stage_real/bootstrap-user"
    rmdir "$stage_real" 2>/dev/null || true
    echo "Release ready: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    exit 0
  fi
  sleep 5
done

compose ps
compose logs --tail=200 api worker migrate object-store-bootstrap gateway
false
