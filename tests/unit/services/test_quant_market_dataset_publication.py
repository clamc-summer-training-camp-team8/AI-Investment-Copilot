from __future__ import annotations

import json
import shutil
from hashlib import sha256
from pathlib import Path

import pytest

from app.core.config import PROJECT_ROOT, settings
from app.services import quant as quant_service
from app.services.market_data import MarketDataError
from app.services.quant import (
    configured_default_market_dataset_id,
    register_market_dataset,
    validate_market_dataset,
)
from tests.fakes import build_fake_uow

V3_DATASET_ID = "MDS-akshare-qfq-tuaremax10000-20260831-v3"
V3_MANIFEST = (
    PROJECT_ROOT / "real_data" / "quant" / "akshare-qfq-tuaremax10000-20260831-v3" / "manifest.json"
)
V3_MANIFEST_SHA256 = "2d53632169f9fc7156feaaf91c002acea468217c9827917c48b30d0e9b2676db"
OLD_MANIFEST = (
    PROJECT_ROOT / "real_data" / "quant" / "akshare-qfq-tushare120-20260830-v1" / "manifest.json"
)


def test_候选可按审批编号和哈希完成只读发布校验() -> None:
    record = validate_market_dataset(
        V3_MANIFEST,
        expected_sha256=V3_MANIFEST_SHA256,
        expected_dataset_id=V3_DATASET_ID,
        frozen_by="release-test",
    )

    assert record.dataset_id == V3_DATASET_ID
    assert record.manifest_sha256 == V3_MANIFEST_SHA256
    assert record.capabilities["a_share_point_in_time_market_cap"] is True


def test_数据中心详情逐项核验冻结子资产并展示研究边界() -> None:
    uow = build_fake_uow()
    registered = register_market_dataset(
        uow,
        manifest_path=V3_MANIFEST,
        expected_sha256=V3_MANIFEST_SHA256,
        expected_dataset_id=V3_DATASET_ID,
        frozen_by="release-test",
    )

    detail = quant_service.market_dataset_detail(
        uow, dataset_id=registered.dataset_id, requested_by="researcher-1"
    )

    assert detail["manifest_verified"] is True
    assert detail["assets"]
    assert all(item["verified"] for item in detail["assets"])
    assert detail["source_priority"]
    assert detail["available_signal_sets"] == []
    assert detail["backtest_count"] == 0


def test_候选登记不会把最新记录猜成默认版本(monkeypatch: pytest.MonkeyPatch) -> None:
    uow = build_fake_uow()
    register_market_dataset(
        uow,
        manifest_path=V3_MANIFEST,
        expected_sha256=V3_MANIFEST_SHA256,
        expected_dataset_id=V3_DATASET_ID,
        frozen_by="release-test",
    )
    monkeypatch.setattr(settings, "quant_default_market_manifest", OLD_MANIFEST)

    assert configured_default_market_dataset_id(uow) is None

    old = register_market_dataset(
        uow,
        manifest_path=OLD_MANIFEST,
        frozen_by="release-test",
    )
    assert configured_default_market_dataset_id(uow) == old.dataset_id


def test_审批哈希不匹配时拒绝登记() -> None:
    with pytest.raises(MarketDataError, match="发布审批值不一致"):
        validate_market_dataset(
            V3_MANIFEST,
            expected_sha256="0" * 64,
            expected_dataset_id=V3_DATASET_ID,
            frozen_by="release-test",
        )


def test_同一数据集编号出现不同清单哈希时拒绝覆盖(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "project"
    source = PROJECT_ROOT / "real_data" / "quant" / "akshare-qfq-tushare120-20260830-v1"
    destination = project_root / "real_data" / "quant" / "candidate"
    shutil.copytree(source, destination)
    manifest = destination / "manifest.json"
    monkeypatch.setattr(quant_service, "PROJECT_ROOT", project_root)
    uow = build_fake_uow()

    first_sha256 = sha256(manifest.read_bytes()).hexdigest()
    first = register_market_dataset(
        uow,
        manifest_path=manifest,
        expected_sha256=first_sha256,
        frozen_by="release-test",
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["limitations"] = [*payload.get("limitations", []), "test-only manifest drift"]
    manifest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(MarketDataError, match="清单哈希不同"):
        register_market_dataset(uow, manifest_path=manifest, frozen_by="release-test")
    assert uow.quant.get_market_dataset(first.dataset_id) == first


def test_受治理目录之外的清单拒绝发布(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")

    with pytest.raises(MarketDataError, match="real_data/quant"):
        validate_market_dataset(manifest, frozen_by="release-test")
