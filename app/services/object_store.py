"""S3-compatible immutable source archive; database stores keys, never credentials or blobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol, cast

import boto3  # type: ignore[import-untyped]
from botocore.client import Config  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from app.core.config import Settings


class ObjectStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredObject:
    object_key: str
    version_id: str | None
    etag: str | None


class ObjectStore(Protocol):
    def ensure_bucket(self) -> None: ...
    def put_immutable(
        self, *, path: Path, object_key: str, content_hash: str, media_type: str | None
    ) -> StoredObject: ...
    def download(
        self, *, object_key: str, destination: Path, version_id: str | None = None
    ) -> None: ...
    def exists(self, *, object_key: str, version_id: str | None = None) -> bool: ...
    def configure_lifecycle(self) -> None: ...


class S3ObjectStore:
    def __init__(self, settings: Settings) -> None:
        self._bucket = settings.object_store_bucket
        self._retention_days = settings.object_store_retention_days
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.object_store_endpoint,
            aws_access_key_id=settings.object_store_access_key,
            aws_secret_access_key=settings.object_store_secret_key.get_secret_value(),
            region_name=settings.object_store_region,
            use_ssl=settings.object_store_secure,
            config=Config(
                signature_version="s3v4",
                connect_timeout=2,
                read_timeout=5,
                retries={"max_attempts": 1, "mode": "standard"},
                s3={"addressing_style": "path"},
            ),
        )

    def ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except Exception:
            try:
                self._client.create_bucket(Bucket=self._bucket, ObjectLockEnabledForBucket=True)
            except Exception as exc:
                raise ObjectStoreError(f"无法创建或访问对象存储 bucket: {self._bucket}") from exc
        try:
            self._client.put_bucket_versioning(
                Bucket=self._bucket, VersioningConfiguration={"Status": "Enabled"}
            )
            self._client.put_object_lock_configuration(
                Bucket=self._bucket,
                ObjectLockConfiguration={
                    "ObjectLockEnabled": "Enabled",
                    "Rule": {
                        "DefaultRetention": {
                            "Mode": "GOVERNANCE",
                            "Days": self._retention_days,
                        }
                    },
                },
            )
        except Exception as exc:
            raise ObjectStoreError("无法启用对象版本控制") from exc
        self.configure_lifecycle()

    def configure_lifecycle(self) -> None:
        """Retain current source objects; expire only non-current accidental overwrites."""
        try:
            self._client.put_bucket_lifecycle_configuration(
                Bucket=self._bucket,
                LifecycleConfiguration={
                    "Rules": [
                        {
                            "ID": "retain-current-expire-noncurrent",
                            "Status": "Enabled",
                            "Filter": {"Prefix": ""},
                            "NoncurrentVersionExpiration": {"NoncurrentDays": 365},
                        }
                    ]
                },
            )
        except Exception as exc:
            raise ObjectStoreError("无法配置对象生命周期策略") from exc

    def put_immutable(
        self, *, path: Path, object_key: str, content_hash: str, media_type: str | None
    ) -> StoredObject:
        if self.exists(object_key=object_key):
            head = self._client.head_object(Bucket=self._bucket, Key=object_key)
            existing_hash = (head.get("Metadata") or {}).get("sha256")
            if existing_hash and existing_hash != content_hash:
                raise ObjectStoreError("对象键已存在但内容哈希不一致")
            return StoredObject(object_key, head.get("VersionId"), _clean_etag(head.get("ETag")))
        try:
            with path.open("rb") as handle:
                result = self._client.put_object(
                    Bucket=self._bucket,
                    Key=object_key,
                    Body=handle,
                    ContentType=media_type or "application/octet-stream",
                    Metadata={"sha256": content_hash},
                )
        except Exception as exc:
            raise ObjectStoreError(f"原文件归档失败: {object_key}") from exc
        return StoredObject(object_key, result.get("VersionId"), _clean_etag(result.get("ETag")))

    def download(
        self, *, object_key: str, destination: Path, version_id: str | None = None
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        args = {"Bucket": self._bucket, "Key": object_key}
        if version_id:
            args["VersionId"] = version_id
        try:
            response = self._client.get_object(**args)
            with destination.open("xb") as handle:
                for chunk in iter(lambda: response["Body"].read(1024 * 1024), b""):
                    handle.write(chunk)
        except Exception as exc:
            destination.unlink(missing_ok=True)
            raise ObjectStoreError(f"无法读取归档原文件: {object_key}") from exc

    def exists(self, *, object_key: str, version_id: str | None = None) -> bool:
        args = {"Bucket": self._bucket, "Key": object_key}
        if version_id:
            args["VersionId"] = version_id
        try:
            self._client.head_object(**args)
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise ObjectStoreError(f"无法检查对象: {object_key}") from exc

    def ready(self) -> bool:
        try:
            self._client.head_bucket(Bucket=self._bucket)
            return True
        except Exception as exc:
            raise ObjectStoreError(f"对象存储 bucket 不可用: {self._bucket}") from exc

    def version_manifest(self) -> dict[str, object]:
        """Return a deterministic inventory suitable for backup/recovery verification."""
        versions: list[dict[str, object]] = []
        try:
            paginator = self._client.get_paginator("list_object_versions")
            for page in paginator.paginate(Bucket=self._bucket):
                for item in page.get("Versions", []):
                    versions.append(
                        {
                            "kind": "object",
                            "key": item["Key"],
                            "version_id": item["VersionId"],
                            "etag": _clean_etag(item.get("ETag")),
                            "size": item.get("Size", 0),
                            "is_latest": bool(item.get("IsLatest")),
                            "last_modified": _iso_datetime(item.get("LastModified")),
                        }
                    )
                for item in page.get("DeleteMarkers", []):
                    versions.append(
                        {
                            "kind": "delete_marker",
                            "key": item["Key"],
                            "version_id": item["VersionId"],
                            "is_latest": bool(item.get("IsLatest")),
                            "last_modified": _iso_datetime(item.get("LastModified")),
                        }
                    )
        except Exception as exc:
            raise ObjectStoreError("无法生成对象存储版本清单") from exc
        return {
            "bucket": self._bucket,
            "version_count": len(versions),
            "versions": sorted(
                versions, key=lambda item: (str(item["key"]), str(item["version_id"]))
            ),
        }

    def export_version_archive(self, destination: Path) -> dict[str, object]:
        """Export every object version and return a content-verifiable manifest."""
        destination.mkdir(parents=True, exist_ok=True)
        manifest = self.version_manifest()
        exported: list[dict[str, object]] = []
        for raw in cast(list[dict[str, Any]], manifest["versions"]):
            item = dict(raw)  # keep the deterministic inventory fields
            if item["kind"] == "object":
                key = str(item["key"])
                version_id = str(item["version_id"])
                key_dir = sha256(key.encode("utf-8")).hexdigest()
                filename = f"{sha256(version_id.encode('utf-8')).hexdigest()}.blob"
                relative = Path("objects") / key_dir / filename
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                digest = sha256()
                try:
                    response = self._client.get_object(
                        Bucket=self._bucket, Key=key, VersionId=version_id
                    )
                    body = response["Body"]
                    with target.open("xb") as handle:
                        while chunk := body.read(1024 * 1024):
                            digest.update(chunk)
                            handle.write(chunk)
                except Exception as exc:
                    target.unlink(missing_ok=True)
                    raise ObjectStoreError(f"无法导出对象版本: {key}@{version_id}") from exc
                item["backup_path"] = relative.as_posix()
                item["content_sha256"] = digest.hexdigest()
            exported.append(item)
        return {
            "bucket": self._bucket,
            "version_count": len(exported),
            "versions": exported,
        }


def object_key_for(*, content_hash: str, suffix: str, tenant: str = "local") -> str:
    safe_suffix = suffix.lower() if suffix.lower() in {".pdf", ".docx", ".txt"} else ".bin"
    return f"{tenant}/documents/{content_hash[:2]}/{content_hash}{safe_suffix}"


def _clean_etag(value: str | None) -> str | None:
    return None if value is None else value.strip('"')


def _iso_datetime(value: object) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None
