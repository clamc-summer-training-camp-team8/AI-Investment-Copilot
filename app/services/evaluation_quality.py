"""读取由离线流水线冻结的独立金标质量资产。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class QualityReportUnavailable(RuntimeError):
    pass


def load_gold_quality_report(path: Path) -> dict[str, Any]:
    """读取质量报告；禁止用运行时默认值掩盖缺失或损坏的发布资产。"""

    if not path.is_file():
        raise QualityReportUnavailable(f"金标质量报告不存在：{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QualityReportUnavailable("金标质量报告不可读取或不是合法 JSON") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") not in {
        "gold-quality-v1",
        "gold-quality-v2",
    }:
        raise QualityReportUnavailable("金标质量报告版本不受支持")
    return payload
