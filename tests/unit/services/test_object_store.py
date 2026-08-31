from datetime import UTC, datetime

from app.services.object_store import S3ObjectStore


class FakePaginator:
    def paginate(self, **kwargs):
        assert kwargs == {"Bucket": "copilot-documents"}
        return [
            {
                "Versions": [
                    {
                        "Key": "local/documents/b.txt",
                        "VersionId": "v2",
                        "ETag": '"etag-b"',
                        "Size": 12,
                        "IsLatest": True,
                        "LastModified": datetime(2026, 8, 13, tzinfo=UTC),
                    },
                    {
                        "Key": "local/documents/a.txt",
                        "VersionId": "v1",
                        "ETag": '"etag-a"',
                        "Size": 8,
                        "IsLatest": False,
                        "LastModified": datetime(2026, 8, 12, tzinfo=UTC),
                    },
                ],
                "DeleteMarkers": [
                    {
                        "Key": "local/documents/c.txt",
                        "VersionId": "delete-1",
                        "IsLatest": True,
                        "LastModified": datetime(2026, 8, 13, tzinfo=UTC),
                    }
                ],
            }
        ]


class FakeClient:
    def get_paginator(self, name: str):
        assert name == "list_object_versions"
        return FakePaginator()


def test_object_version_manifest_is_complete_and_deterministic() -> None:
    store = object.__new__(S3ObjectStore)
    store._bucket = "copilot-documents"
    store._client = FakeClient()

    manifest = store.version_manifest()

    assert manifest["version_count"] == 3
    assert [item["key"] for item in manifest["versions"]] == [
        "local/documents/a.txt",
        "local/documents/b.txt",
        "local/documents/c.txt",
    ]
    assert manifest["versions"][1]["etag"] == "etag-b"
    assert manifest["versions"][2]["kind"] == "delete_marker"
