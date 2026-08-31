#!/usr/bin/env bash
set -Eeuo pipefail

deploy_dir="${DEPLOY_DIR:-/opt/ai-investment-copilot/deploy}"
backup_root="${BACKUP_ROOT:-/opt/ai-investment-copilot/backups}"
env_file="${INTEGRATION_ENV_FILE:-$deploy_dir/.env.integration}"
release_file="${INTEGRATION_RELEASE_FILE:-$deploy_dir/release.env}"
compose_file="$deploy_dir/docker-compose.integration.yml"

test -f "$compose_file"
test -f "$env_file"
test -f "$release_file"
mkdir -p "$backup_root"

compose=(docker compose -f "$compose_file" --env-file "$env_file" --env-file "$release_file")
mapfile -t database_target < <(
  "${compose[@]}" run --rm --no-deps api python -m scripts.resolve_database_target
)
if [[ "${#database_target[@]}" -ne 2 ]]; then
  echo "无法从在线 DATABASE_URL 解析唯一的数据库用户和数据库名。" >&2
  exit 1
fi
database_user="${database_target[0]}"
database_name="${database_target[1]}"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_dir="$backup_root/$stamp"
mkdir -m 0700 "$backup_dir"

"${compose[@]}" exec -T postgres \
  pg_dump -U "$database_user" -d "$database_name" --format=custom --compress=9 \
  > "$backup_dir/database.dump"
printf 'database_user=%s\ndatabase_name=%s\n' "$database_user" "$database_name" \
  > "$backup_dir/database-target.txt"

"${compose[@]}" run --rm --no-deps --user 0:0 \
  -v "$backup_dir:/backup" \
  object-store-bootstrap \
  python -m scripts.export_object_manifest \
    --output /backup/object-manifest.json \
    --archive-dir /backup/object-archive

"${compose[@]}" config --images | sort -u > "$backup_dir/images.txt"
(
  cd "$backup_dir"
  find . -type f ! -name SHA256SUMS -print0 \
    | sort -z \
    | xargs -0 sha256sum > SHA256SUMS
)

if [[ -n "${OBS_BACKUP_URI:-}" ]]; then
  if ! command -v obsutil >/dev/null 2>&1; then
    echo "OBS_BACKUP_URI 已设置，但服务器未安装 obsutil。" >&2
    exit 1
  fi
  obsutil cp "$backup_dir" "${OBS_BACKUP_URI%/}/$stamp" -r -f
fi

echo "Backup completed: $backup_dir"
