#!/usr/bin/env bash
set -Eeuo pipefail

backup_root="${BACKUP_ROOT:-/opt/ai-investment-copilot/backups}"
requested="${1:-}"
if [[ -z "$requested" ]]; then
  echo "Usage: $0 <backup-directory>" >&2
  exit 2
fi

backup_root_real="$(realpath "$backup_root")"
backup_dir="$(realpath "$requested")"
case "$backup_dir/" in
  "$backup_root_real"/*) ;;
  *) echo "仅允许验证 $backup_root_real 下的备份。" >&2; exit 2 ;;
esac

test -s "$backup_dir/database.dump"
test -s "$backup_dir/object-manifest.json"
test -s "$backup_dir/SHA256SUMS"
(
  cd "$backup_dir"
  sha256sum --check SHA256SUMS
)

suffix="$(date -u +%Y%m%d%H%M%S)-$$"
container="copilot-integration-restore-$suffix"
cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker run -d --name "$container" \
  -e POSTGRES_USER=copilot \
  -e POSTGRES_PASSWORD=restore-drill-only \
  -e POSTGRES_DB=copilot_restore \
  pgvector/pgvector:0.8.6-pg16-bookworm >/dev/null

for attempt in $(seq 1 30); do
  if docker exec "$container" pg_isready -U copilot -d copilot_restore >/dev/null 2>&1; then
    break
  fi
  if [[ "$attempt" == 30 ]]; then
    echo "隔离恢复数据库未就绪。" >&2
    exit 1
  fi
  sleep 2
done

docker cp "$backup_dir/database.dump" "$container:/tmp/database.dump"
docker exec "$container" pg_restore \
  -U copilot -d copilot_restore --clean --if-exists /tmp/database.dump

alembic_head="$(docker exec "$container" psql -U copilot -d copilot_restore -Atc \
  'select version_num from alembic_version limit 1;')"
test -n "$alembic_head"

rows_file="$(mktemp)"
trap 'rm -f "$rows_file"; cleanup' EXIT
docker exec "$container" psql -U copilot -d copilot_restore -c \
  "COPY (
     SELECT object_key, COALESCE(object_version_id, ''), content_hash
     FROM document_revision
     WHERE object_key IS NOT NULL
     ORDER BY object_key, object_version_id
   ) TO STDOUT WITH (FORMAT CSV, HEADER TRUE)" > "$rows_file"

checked_objects="$(python3 - "$backup_dir" "$rows_file" <<'PY'
import csv
import hashlib
import json
import sys
from pathlib import Path

backup = Path(sys.argv[1]).resolve()
rows_path = Path(sys.argv[2])
manifest = json.loads((backup / "object-manifest.json").read_text(encoding="utf-8"))
by_version = {}
latest = {}
for item in manifest.get("versions", []):
    if item.get("kind") != "object":
        continue
    key = str(item["key"])
    by_version[(key, str(item["version_id"]))] = item
    if item.get("is_latest"):
        latest[key] = item

checked = 0
with rows_path.open(newline="", encoding="utf-8") as handle:
    for row in csv.DictReader(handle):
        key = row["object_key"]
        version_id = row["coalesce"]
        item = by_version.get((key, version_id)) if version_id else latest.get(key)
        if item is None:
            raise SystemExit(f"对象版本不在归档中: {key}@{version_id}")
        archived = (backup / "object-archive" / str(item["backup_path"])).resolve()
        archived.relative_to(backup)
        digest = hashlib.sha256()
        with archived.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        actual = digest.hexdigest()
        if actual != item.get("content_sha256") or actual != row["content_hash"]:
            raise SystemExit(f"对象内容哈希不一致: {key}@{version_id}")
        checked += 1
print(checked)
PY
)"

echo "Restore drill passed: alembic=$alembic_head objects=$checked_objects backup=$backup_dir"
