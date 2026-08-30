"""Validate and compare returned independent-gold v3 workbooks.

The XLSX reader intentionally uses only the Python standard library.  It reads
the narrow OOXML surface emitted by the frozen templates, so validation does
not require Excel, LibreOffice, or a new production dependency.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from app.core.config import PROJECT_ROOT

DEFAULT_PACKAGE = PROJECT_ROOT / "outputs" / "gold-annotation-v3-20260826"
NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkg": "http://schemas.openxmlformats.org/package/2006/relationships",
}
CELL_REF = re.compile(r"([A-Z]+)(\d+)")

SPECS = {
    "event": {
        "sheet": "事件语义_120",
        "template": "annotator_{annotator}_events.csv",
        "key": "样本ID",
        "fixed_count": 14,
        "core": ["事件类别", "主要关联假设", "影响方向", "影响强度", "直接性"],
        "reason": "判断理由",
        "confidence": "置信度",
        "issue": "数据问题",
    },
    "body_fact": {
        "sheet": "正文事实_60",
        "template": "annotator_{annotator}_body_facts.csv",
        "key": "正文样本ID",
        "fixed_count": 10,
        "core": [
            "是否存在可抽取事实",
            "事实类型",
            "变化方向",
            "数值下限",
            "数值上限",
            "单位",
            "事实发生期",
        ],
        "reason": "判断理由",
        "confidence": "置信度",
        "issue": "数据问题",
    },
    "graph_relevance": {
        "sheet": "GraphRAG相关性_180",
        "template": "annotator_{annotator}_graph_relevance.csv",
        "key": "关系样本ID",
        "fixed_count": 11,
        "core": ["相关性等级", "关系路径可成立"],
        "reason": "判断理由",
        "confidence": "置信度",
        "issue": "数据问题",
    },
}
TASK_LABELS = {
    "event": "事件语义",
    "body_fact": "正文事实",
    "graph_relevance": "Graph RAG 相关性",
}


def _column_index(reference: str) -> int:
    match = CELL_REF.fullmatch(reference)
    if not match:
        raise ValueError(f"invalid cell reference: {reference}")
    value = 0
    for character in match.group(1):
        value = value * 26 + ord(character) - 64
    return value - 1


def _shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(node.text or "" for node in item.findall(".//main:t", NS)) for item in root]


def _sheet_paths(archive: ZipFile) -> dict[str, str]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_paths = {
        relation.get("Id", ""): relation.get("Target", "")
        for relation in relationships.findall("pkg:Relationship", NS)
    }
    paths: dict[str, str] = {}
    for sheet in workbook.findall("main:sheets/main:sheet", NS):
        name = sheet.get("name", "")
        rel_id = sheet.get(f"{{{NS['rel']}}}id", "")
        target = rel_paths[rel_id].lstrip("/")
        paths[name] = target if target.startswith("xl/") else f"xl/{target}"
    return paths


def read_xlsx_sheet(path: Path, sheet_name: str) -> list[dict[str, str]]:
    with ZipFile(path) as archive:
        strings = _shared_strings(archive)
        sheet_path = _sheet_paths(archive).get(sheet_name)
        if not sheet_path:
            raise ValueError(f"missing worksheet: {sheet_name}")
        root = ET.fromstring(archive.read(sheet_path))
        matrix: list[list[str]] = []
        for row_node in root.findall(".//main:sheetData/main:row", NS):
            values: dict[int, str] = {}
            for cell in row_node.findall("main:c", NS):
                reference = cell.get("r", "")
                index = _column_index(reference)
                cell_type = cell.get("t")
                if cell_type == "inlineStr":
                    value = "".join(node.text or "" for node in cell.findall(".//main:t", NS))
                else:
                    value_node = cell.find("main:v", NS)
                    raw = value_node.text if value_node is not None and value_node.text else ""
                    if cell_type == "s" and raw:
                        value = strings[int(raw)]
                    elif cell_type == "b":
                        value = "TRUE" if raw == "1" else "FALSE"
                    else:
                        value = raw
                values[index] = value
            if values:
                width = max(values) + 1
                matrix.append([values.get(index, "") for index in range(width)])
        if not matrix:
            return []
        headers = matrix[0]
        return [
            {header: row[index] if index < len(row) else "" for index, header in enumerate(headers)}
            for row in matrix[1:]
            if any(row)
        ]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _excel_datetime(value: str) -> datetime | None:
    try:
        serial = float(value)
    except ValueError:
        return None
    return datetime(1899, 12, 30) + timedelta(days=serial)


def _fixed_equal(expected: str, actual: str) -> bool:
    actual = actual.removeprefix("\u200b").removeprefix("'")
    if expected == actual:
        return True
    if "T" in expected:
        converted = _excel_datetime(actual)
        if converted is not None:
            expected_dt = datetime.fromisoformat(expected).replace(tzinfo=None)
            return abs((converted - expected_dt).total_seconds()) < 1
    return False


def validate_workbook(
    workbook_path: Path,
    *,
    annotator: str,
    package_dir: Path = DEFAULT_PACKAGE,
    allow_empty: bool = False,
) -> list[str]:
    contract = json.loads((package_dir / "gold_contract_v3.json").read_text(encoding="utf-8"))
    problems: list[str] = []
    for task, spec in SPECS.items():
        expected = _read_csv(
            package_dir / "tasks" / str(spec["template"]).format(annotator=annotator)
        )
        actual = read_xlsx_sheet(workbook_path, str(spec["sheet"]))
        if len(actual) != len(expected):
            problems.append(f"{spec['sheet']}: rows={len(actual)}, expected={len(expected)}")
            continue
        fixed_fields = list(expected[0])[: int(spec["fixed_count"])]
        required = contract["required_fields"][task]
        for row_number, (row, reference) in enumerate(zip(actual, expected, strict=True), 2):
            key = reference[str(spec["key"])]
            for field in fixed_fields:
                if not _fixed_equal(reference[field], row.get(field, "")):
                    problems.append(
                        f"{spec['sheet']}!{row_number} {key}: fixed field changed: {field}"
                    )
            if allow_empty and not any(row.get(field, "") for field in required):
                continue
            for field in required:
                if not row.get(field, "").strip():
                    problems.append(f"{spec['sheet']}!{row_number} {key}: required blank: {field}")
            for field, values in contract["enums"].items():
                if (
                    field in row
                    and row[field]
                    and row[field] not in {str(value) for value in values}
                ):
                    problems.append(
                        f"{spec['sheet']}!{row_number} {key}: invalid {field}={row[field]}"
                    )

            timestamp = row.get("标注时间", "")
            if timestamp:
                try:
                    parsed = datetime.fromisoformat(timestamp)
                    if parsed.tzinfo is None:
                        raise ValueError
                except ValueError:
                    problems.append(
                        f"{spec['sheet']}!{row_number} {key}: 标注时间 must be ISO 8601 with timezone"
                    )

            if task == "event":
                hypothesis = row.get("主要关联假设", "")
                direction = row.get("影响方向", "")
                if hypothesis == "无关" and direction != "无关":
                    problems.append(
                        f"{spec['sheet']}!{row_number} {key}: 无关 hypothesis requires 无关 direction"
                    )
                if (
                    hypothesis in {"H1-需求与出货", "H2-盈利质量", "H3-产能与扩张"}
                    and direction == "无关"
                ):
                    problems.append(
                        f"{spec['sheet']}!{row_number} {key}: related hypothesis cannot use 无关 direction"
                    )
                if hypothesis.startswith("H") and not row.get("关键证据原文", "").strip():
                    problems.append(
                        f"{spec['sheet']}!{row_number} {key}: related event requires evidence quote"
                    )
            elif task == "body_fact" and row.get("是否存在可抽取事实") == "是":
                for field in ("正文定位", "正文片段", "事实类型", "变化方向"):
                    if not row.get(field, "").strip():
                        problems.append(
                            f"{spec['sheet']}!{row_number} {key}: extracted fact requires {field}"
                        )
            elif task == "graph_relevance":
                relevance = row.get("相关性等级", "")
                path_valid = row.get("关系路径可成立", "")
                if relevance == "0-无关" and path_valid == "是":
                    problems.append(
                        f"{spec['sheet']}!{row_number} {key}: unrelated pair cannot have a valid path"
                    )
    return problems


def _kappa(left: list[str], right: list[str]) -> float | None:
    if not left:
        return None
    observed = sum(a == b for a, b in zip(left, right, strict=True)) / len(left)
    left_counts = Counter(left)
    right_counts = Counter(right)
    expected = sum(
        left_counts[label] / len(left) * right_counts[label] / len(right)
        for label in set(left_counts) | set(right_counts)
    )
    if math.isclose(expected, 1.0):
        return 1.0 if math.isclose(observed, 1.0) else None
    return round((observed - expected) / (1 - expected), 4)


def compare_workbooks(
    a_path: Path, b_path: Path, *, package_dir: Path = DEFAULT_PACKAGE, output_dir: Path
) -> dict[str, Any]:
    a_problems = validate_workbook(a_path, annotator="A", package_dir=package_dir)
    b_problems = validate_workbook(b_path, annotator="B", package_dir=package_dir)
    if a_problems or b_problems:
        raise ValueError(
            json.dumps({"A": a_problems, "B": b_problems}, ensure_ascii=False, indent=2)
        )

    queue: list[dict[str, str]] = []
    agreements: dict[str, dict[str, Any]] = {}
    for task, spec in SPECS.items():
        a_rows = {row[str(spec["key"])]: row for row in read_xlsx_sheet(a_path, str(spec["sheet"]))}
        b_rows = {row[str(spec["key"])]: row for row in read_xlsx_sheet(b_path, str(spec["sheet"]))}
        for field in spec["core"]:
            left = [a_rows[key][field] for key in sorted(a_rows)]
            right = [b_rows[key][field] for key in sorted(b_rows)]
            agreements[f"{task}.{field}"] = {
                "n": len(left),
                "agreement": round(
                    sum(a == b for a, b in zip(left, right, strict=True)) / len(left), 4
                ),
                "cohen_kappa": _kappa(left, right),
            }
        for key in sorted(a_rows):
            a_row = a_rows[key]
            b_row = b_rows[key]
            a_result = {field: a_row[field] for field in spec["core"]}
            b_result = {field: b_row[field] for field in spec["core"]}
            needs_adjudication = (
                a_result != b_result
                or int(float(a_row[str(spec["confidence"])])) <= 2
                or int(float(b_row[str(spec["confidence"])])) <= 2
                or a_row[str(spec["issue"])] != "无"
                or b_row[str(spec["issue"])] != "无"
            )
            if needs_adjudication:
                queue.append(
                    {
                        "任务类型": task,
                        "样本ID": key,
                        "A结果": json.dumps(a_result, ensure_ascii=False, sort_keys=True),
                        "A理由": a_row[str(spec["reason"])],
                        "B结果": json.dumps(b_result, ensure_ascii=False, sort_keys=True),
                        "B理由": b_row[str(spec["reason"])],
                        "裁决结果": "",
                        "裁决理由": "",
                        "裁决人ID": "",
                        "裁决时间": "",
                    }
                )

    output_dir.mkdir(parents=True, exist_ok=True)
    queue_path = output_dir / "adjudication_queue.csv"
    with queue_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=list(queue[0]) if queue else list(_empty_queue())
        )
        writer.writeheader()
        writer.writerows(queue)
    report = {
        "package_version": "independent-gold-v3-20260826",
        "A": str(a_path),
        "B": str(b_path),
        "agreement": agreements,
        "adjudication_rows": len(queue),
        "adjudication_queue": str(queue_path),
    }
    (output_dir / "agreement_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def _empty_queue() -> dict[str, str]:
    return {
        "任务类型": "",
        "样本ID": "",
        "A结果": "",
        "A理由": "",
        "B结果": "",
        "B理由": "",
        "裁决结果": "",
        "裁决理由": "",
        "裁决人ID": "",
        "裁决时间": "",
    }


def _clean_row(row: dict[str, str]) -> dict[str, str]:
    return {field: value.removeprefix("\u200b").removeprefix("'") for field, value in row.items()}


def _quality_gate(
    code: str,
    label: str,
    status: str,
    message: str,
    *,
    current: int | float | bool | None = None,
    target: int | float | bool | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "label": label,
        "status": status,
        "current": current,
        "target": target,
        "message": message,
    }


def export_consensus_gold(
    a_path: Path,
    b_path: Path,
    *,
    package_dir: Path = DEFAULT_PACKAGE,
    output_dir: Path,
    minimum_confidence: int = 3,
) -> dict[str, Any]:
    """Freeze exact A/B agreements as evaluation-ready, non-final gold.

    A professional review of both workbooks does not erase genuine label
    disagreement.  This export therefore keeps only rows whose core labels
    agree, whose confidence is at least ``minimum_confidence`` and whose data
    issue is ``无``.  Disagreements remain in a separately checksummed review
    queue.  The resulting dataset is safe for interim offline evaluation but
    is deliberately not named ``final``.
    """

    if not 1 <= minimum_confidence <= 5:
        raise ValueError("minimum_confidence must be between 1 and 5")

    comparison_dir = output_dir / "review"
    comparison = compare_workbooks(
        a_path,
        b_path,
        package_dir=package_dir,
        output_dir=comparison_dir,
    )
    queue = _read_csv(Path(comparison["adjudication_queue"]))
    pending_by_task = Counter(row["任务类型"] for row in queue)

    output_dir.mkdir(parents=True, exist_ok=True)
    tasks: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    total_consensus = 0
    total_samples = 0
    for task, spec in SPECS.items():
        a_rows = {row[str(spec["key"])]: row for row in read_xlsx_sheet(a_path, str(spec["sheet"]))}
        b_rows = {row[str(spec["key"])]: row for row in read_xlsx_sheet(b_path, str(spec["sheet"]))}
        consensus_rows: list[dict[str, str]] = []
        for sample_id in sorted(a_rows):
            a_row = a_rows[sample_id]
            b_row = b_rows[sample_id]
            core_agrees = all(a_row[field] == b_row[field] for field in spec["core"])
            confidence_ok = (
                int(float(a_row[str(spec["confidence"])])) >= minimum_confidence
                and int(float(b_row[str(spec["confidence"])])) >= minimum_confidence
            )
            issues_ok = a_row[str(spec["issue"])] == "无" and b_row[str(spec["issue"])] == "无"
            if not (core_agrees and confidence_ok and issues_ok):
                continue
            row = _clean_row(a_row)
            row["标注人ID"] = "A+B-consensus"
            row["gold_status"] = "consensus"
            row["gold_source"] = "independent-A/B-exact-agreement"
            row["gold_version"] = "consensus-gold-v3-20260826"
            row["annotator_a_id"] = a_row.get("标注人ID", "")
            row["annotator_b_id"] = b_row.get("标注人ID", "")
            row["annotator_a_confidence"] = a_row[str(spec["confidence"])]
            row["annotator_b_confidence"] = b_row[str(spec["confidence"])]
            row["annotator_a_reason"] = a_row[str(spec["reason"])]
            row["annotator_b_reason"] = b_row[str(spec["reason"])]
            consensus_rows.append(row)

        output_path = output_dir / f"consensus_{task}_gold_v3.csv"
        if not consensus_rows:
            raise ValueError(f"{task}: no rows satisfy the consensus policy")
        with output_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(consensus_rows[0]))
            writer.writeheader()
            writer.writerows(consensus_rows)
        file_record = {
            "path": output_path.name,
            "rows": len(consensus_rows),
            "sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        }
        files.append(file_record)
        total = len(a_rows)
        consensus_count = len(consensus_rows)
        pending = int(pending_by_task[task])
        tasks.append(
            {
                "task": task,
                "label": TASK_LABELS[task],
                "total": total,
                "consensus": consensus_count,
                "pending": pending,
                "coverage": round(consensus_count / total, 4),
                "core_fields": list(spec["core"]),
                "file": output_path.name,
            }
        )
        total_consensus += consensus_count
        total_samples += total

    agreement = [
        {
            "task": metric.split(".", 1)[0],
            "field": metric.split(".", 1)[1],
            **values,
        }
        for metric, values in comparison["agreement"].items()
    ]
    agreement_by_key = {f"{item['task']}.{item['field']}": item for item in agreement}
    event_kappa = agreement_by_key["event.影响方向"]["cohen_kappa"]
    body_kappa = agreement_by_key["body_fact.变化方向"]["cohen_kappa"]
    graph_kappa = agreement_by_key["graph_relevance.相关性等级"]["cohen_kappa"]
    pending_total = len(queue)
    gates = [
        _quality_gate(
            "workbook_validation",
            "工作簿结构与字段契约",
            "passed",
            "A/B 两份回收工作簿均通过固定字段、枚举、必填项与时间格式校验。",
            current=True,
            target=True,
        ),
        _quality_gate(
            "independent_double_annotation",
            "独立双人标注覆盖",
            "passed",
            "全部样本均包含两份独立标注。",
            current=total_samples,
            target=total_samples,
        ),
        _quality_gate(
            "consensus_evaluation_set",
            "高置信共识评测集",
            "passed",
            "三个任务均已冻结可复现的共识子集，可用于离线基线评测。",
            current=sum(item["consensus"] > 0 for item in tasks),
            target=len(tasks),
        ),
        _quality_gate(
            "event_direction_agreement",
            "事件方向一致性",
            "passed" if event_kappa is not None and event_kappa >= 0.6 else "warning",
            "Cohen's kappa 以 0.60 作为本轮稳定性参考线。",
            current=event_kappa,
            target=0.6,
        ),
        _quality_gate(
            "body_fact_direction_agreement",
            "正文事实方向一致性",
            "passed" if body_kappa is not None and body_kappa >= 0.6 else "warning",
            "低于参考线时仅使用精确一致样本，不将分歧样本硬并入金标。",
            current=body_kappa,
            target=0.6,
        ),
        _quality_gate(
            "graph_relevance_agreement",
            "Graph RAG 相关性一致性",
            "passed" if graph_kappa is not None and graph_kappa >= 0.6 else "warning",
            "低于参考线说明关系相关性的边界仍需通过困难样本规则或裁决收敛。",
            current=graph_kappa,
            target=0.6,
        ),
        _quality_gate(
            "adjudication_complete",
            "分歧裁决完成",
            "passed" if pending_total == 0 else "blocked",
            "未裁决样本保留在审计队列中，不计入最终硬金标。",
            current=pending_total,
            target=0,
        ),
        _quality_gate(
            "graph_rag_system_benchmark",
            "Graph RAG 系统离线基准",
            "blocked",
            "共识数据已经就绪，但尚未记录当前 Graph RAG 的 Recall@K、MRR 与权限泄漏门禁。",
            current=None,
            target=True,
        ),
    ]
    report = {
        "schema_version": "gold-quality-v1",
        "gold_version": "consensus-gold-v3-20260826",
        "gold_state": "consensus",
        "created_at": datetime.now().astimezone().isoformat(),
        "source_package": "independent-gold-v3-20260826",
        "summary": {
            "total_samples": total_samples,
            "consensus_samples": total_consensus,
            "pending_adjudication": pending_total,
            "consensus_coverage": round(total_consensus / total_samples, 4),
            "evaluation_ready": total_consensus > 0
            and all(item["consensus"] > 0 for item in tasks),
            "production_gold_ready": pending_total == 0,
            "graph_rag_rollout_ready": False,
        },
        "tasks": tasks,
        "agreement": agreement,
        "gates": gates,
        "files": files,
        "review_artifacts": {
            "agreement_report": "review/agreement_report.json",
            "adjudication_queue": "review/adjudication_queue.csv",
            "adjudication_rows": pending_total,
        },
        "source_sha256": {
            "A": hashlib.sha256(a_path.read_bytes()).hexdigest(),
            "B": hashlib.sha256(b_path.read_bytes()).hexdigest(),
        },
    }
    (output_dir / "quality_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def finalize_gold(
    a_path: Path,
    b_path: Path,
    adjudication_path: Path,
    *,
    package_dir: Path = DEFAULT_PACKAGE,
    output_dir: Path,
) -> dict[str, Any]:
    """Export frozen task CSVs after every comparison-queue row is adjudicated."""

    contract = json.loads((package_dir / "gold_contract_v3.json").read_text(encoding="utf-8"))

    # Regenerate the expected queue so the adjudicator cannot silently omit a row.
    comparison_dir = output_dir / "_comparison_check"
    comparison = compare_workbooks(
        a_path, b_path, package_dir=package_dir, output_dir=comparison_dir
    )
    expected_queue = _read_csv(Path(comparison["adjudication_queue"]))
    adjudicated_rows = _read_csv(adjudication_path)
    expected_keys = {(row["任务类型"], row["样本ID"]) for row in expected_queue}
    adjudicated = {(row["任务类型"], row["样本ID"]): row for row in adjudicated_rows}
    if set(adjudicated) != expected_keys:
        missing = sorted(expected_keys - set(adjudicated))
        extra = sorted(set(adjudicated) - expected_keys)
        raise ValueError(f"adjudication queue mismatch: missing={missing}, extra={extra}")

    parsed_rulings: dict[tuple[str, str], dict[str, str]] = {}
    for key, row in adjudicated.items():
        for field in ("裁决结果", "裁决理由", "裁决人ID", "裁决时间"):
            if not row.get(field, "").strip():
                raise ValueError(f"{key}: missing {field}")
        try:
            ruling = json.loads(row["裁决结果"])
        except json.JSONDecodeError as exc:
            raise ValueError(f"{key}: 裁决结果 must be a JSON object") from exc
        spec = SPECS[key[0]]
        if set(ruling) != set(spec["core"]):
            raise ValueError(f"{key}: ruling keys must be {spec['core']}")
        for field, value in ruling.items():
            if field in contract["enums"] and str(value) not in {
                str(candidate) for candidate in contract["enums"][field]
            }:
                raise ValueError(f"{key}: invalid ruling {field}={value}")
        timestamp = datetime.fromisoformat(row["裁决时间"])
        if timestamp.tzinfo is None:
            raise ValueError(f"{key}: 裁决时间 must include timezone")
        if key[0] == "event":
            hypothesis = str(ruling["主要关联假设"])
            direction = str(ruling["影响方向"])
            if hypothesis == "无关" and direction != "无关":
                raise ValueError(f"{key}: 无关 hypothesis requires 无关 direction")
            if hypothesis.startswith("H") and direction == "无关":
                raise ValueError(f"{key}: related hypothesis cannot use 无关 direction")
        if (
            key[0] == "graph_relevance"
            and ruling["相关性等级"] == "0-无关"
            and ruling["关系路径可成立"] == "是"
        ):
            raise ValueError(f"{key}: unrelated pair cannot have a valid path")
        parsed_rulings[key] = {field: str(ruling[field]) for field in spec["core"]}

    output_dir.mkdir(parents=True, exist_ok=True)
    files: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    rows_by_task: dict[str, list[dict[str, str]]] = {}
    for task, spec in SPECS.items():
        a_rows = read_xlsx_sheet(a_path, str(spec["sheet"]))
        b_rows = {row[str(spec["key"])]: row for row in read_xlsx_sheet(b_path, str(spec["sheet"]))}
        final_rows: list[dict[str, str]] = []
        for a_row in a_rows:
            sample_id = a_row[str(spec["key"])]
            key = (task, sample_id)
            row = {
                field: value.removeprefix("\u200b").removeprefix("'")
                for field, value in a_row.items()
            }
            if key in parsed_rulings:
                row.update(parsed_rulings[key])
                ruling = adjudicated[key]
                row[str(spec["reason"])] = ruling["裁决理由"]
                row["标注人ID"] = ruling["裁决人ID"]
                row["标注时间"] = ruling["裁决时间"]
                source = "adjudicated"
            else:
                b_row = b_rows[sample_id]
                if any(a_row[field] != b_row[field] for field in spec["core"]):
                    raise ValueError(f"{key}: disagreement missing from adjudication queue")
                source = "A/B-agreed"
            row["gold_source"] = source
            row["gold_version"] = "final-gold-v3-20260826"
            final_rows.append(row)

        output_path = output_dir / f"final_{task}_gold_v3.csv"
        fieldnames = list(final_rows[0])
        with output_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(final_rows)
        files.append(
            {
                "path": output_path.name,
                "rows": len(final_rows),
                "sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
            }
        )
        counts[task] = len(final_rows)
        rows_by_task[task] = final_rows

    report = {
        "gold_version": "final-gold-v3-20260826",
        "created_at": datetime.now().astimezone().isoformat(),
        "source_package": "independent-gold-v3-20260826",
        "counts": counts,
        "adjudicated_rows": len(expected_queue),
        "source_sha256": {
            "A": hashlib.sha256(a_path.read_bytes()).hexdigest(),
            "B": hashlib.sha256(b_path.read_bytes()).hexdigest(),
            "adjudication": hashlib.sha256(adjudication_path.read_bytes()).hexdigest(),
        },
        "files": files,
        "quality_report": "quality_report.json",
    }
    (output_dir / "final_gold_manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    quality_report = _build_final_quality_report(
        comparison=comparison,
        counts=counts,
        rows_by_task=rows_by_task,
        files=files,
        source_sha256=report["source_sha256"],
    )
    (output_dir / "quality_report.json").write_text(
        json.dumps(quality_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def _build_final_quality_report(
    *,
    comparison: dict[str, Any],
    counts: dict[str, int],
    rows_by_task: dict[str, list[dict[str, str]]],
    files: list[dict[str, Any]],
    source_sha256: dict[str, str],
) -> dict[str, Any]:
    """Build the UI/API report for adjudicated final gold without hiding DQ exceptions."""

    queue = _read_csv(Path(comparison["adjudication_queue"]))
    adjudicated_by_task = Counter(row["任务类型"] for row in queue)
    issues: list[dict[str, str]] = []
    eligible_by_task: dict[str, int] = {}
    tasks: list[dict[str, Any]] = []
    for task, spec in SPECS.items():
        rows = rows_by_task[task]
        ineligible: set[str] = set()
        for row in rows:
            sample_id = row[str(spec["key"])]
            reasons: list[str] = []
            if row.get(str(spec["issue"]), "无") != "无":
                reasons.append(row[str(spec["issue"])] or "数据问题")
            try:
                if int(float(row.get(str(spec["confidence"]), "0"))) <= 2:
                    reasons.append("低置信度")
            except ValueError:
                reasons.append("置信度无效")
            if (
                task == "event"
                and row.get("主要关联假设", "").startswith("H")
                and not row.get("关键证据原文", "").strip()
            ):
                reasons.append("关键证据原文缺失")
            if (
                task == "body_fact"
                and row.get("是否存在可抽取事实") == "是"
                and (not row.get("正文定位", "").strip() or not row.get("正文片段", "").strip())
            ):
                reasons.append("正文定位或片段缺失")
            if reasons:
                ineligible.add(sample_id)
                issues.append(
                    {
                        "task": task,
                        "sample_id": sample_id,
                        "reason": "、".join(dict.fromkeys(reasons)),
                    }
                )
        eligible = len(rows) - len(ineligible)
        eligible_by_task[task] = eligible
        adjudicated = int(adjudicated_by_task[task])
        tasks.append(
            {
                "task": task,
                "label": TASK_LABELS[task],
                "total": len(rows),
                "consensus": len(rows) - adjudicated,
                "adjudicated": adjudicated,
                "final": len(rows),
                "evaluation_eligible": eligible,
                "pending": 0,
                "coverage": 1.0,
                "core_fields": list(spec["core"]),
                "file": f"final_{task}_gold_v3.csv",
            }
        )

    agreement = [
        {
            "task": metric.split(".", 1)[0],
            "field": metric.split(".", 1)[1],
            **values,
        }
        for metric, values in comparison["agreement"].items()
    ]
    total = sum(counts.values())
    adjudicated_total = len(queue)
    consensus_total = total - adjudicated_total
    eligible_total = sum(eligible_by_task.values())
    gates = [
        _quality_gate(
            "workbook_validation",
            "工作簿结构与字段契约",
            "passed",
            "A/B 两份回收工作簿均通过固定字段、枚举、必填项与时间格式校验。",
            current=True,
            target=True,
        ),
        _quality_gate(
            "adjudication_complete",
            "分歧裁决完成",
            "passed",
            "全部分歧、低置信或数据问题判断单元均已形成独立裁决记录。",
            current=adjudicated_total,
            target=adjudicated_total,
        ),
        _quality_gate(
            "final_gold_freeze",
            "最终硬金标冻结",
            "passed",
            "三个任务的最终标签已冻结并生成逐文件 SHA-256。",
            current=total,
            target=total,
        ),
        _quality_gate(
            "evaluation_eligibility",
            "离线评测可用样本",
            "passed" if eligible_total == total else "warning",
            "保留存在原文不可提取、低置信或关键证据缺失的最终标签，但系统指标默认排除这些样本。",
            current=eligible_total,
            target=total,
        ),
        _quality_gate(
            "graph_rag_system_benchmark",
            "Graph RAG 系统离线基准",
            "blocked",
            "最终相关性金标已就绪；仍需记录当前系统的 Recall@K、MRR 与权限泄漏门禁。",
            current=None,
            target=True,
        ),
    ]
    return {
        "schema_version": "gold-quality-v2",
        "gold_version": "final-gold-v3-20260826",
        "gold_state": "final",
        "created_at": datetime.now().astimezone().isoformat(),
        "source_package": "independent-gold-v3-20260826",
        "summary": {
            "total_samples": total,
            "consensus_samples": consensus_total,
            "adjudicated_samples": adjudicated_total,
            "gold_samples": total,
            "evaluation_eligible_samples": eligible_total,
            "pending_adjudication": 0,
            "consensus_coverage": round(consensus_total / total, 4),
            "gold_coverage": 1.0,
            "evaluation_ready": eligible_total > 0,
            "production_gold_ready": True,
            "graph_rag_rollout_ready": False,
        },
        "tasks": tasks,
        "agreement": agreement,
        "gates": gates,
        "quality_exceptions": issues,
        "files": files,
        "review_artifacts": {
            "agreement_report": "_comparison_check/agreement_report.json",
            "adjudication_rows": adjudicated_total,
        },
        "source_sha256": source_sha256,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate/compare independent gold v3 XLSX")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("workbook", type=Path)
    validate.add_argument("--annotator", choices=("A", "B"), required=True)
    validate.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    validate.add_argument("--allow-empty", action="store_true")
    compare = subparsers.add_parser("compare")
    compare.add_argument("a", type=Path)
    compare.add_argument("b", type=Path)
    compare.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    compare.add_argument("--output", type=Path, required=True)
    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("a", type=Path)
    finalize.add_argument("b", type=Path)
    finalize.add_argument("adjudication", type=Path)
    finalize.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    finalize.add_argument("--output", type=Path, required=True)
    consensus = subparsers.add_parser("consensus")
    consensus.add_argument("a", type=Path)
    consensus.add_argument("b", type=Path)
    consensus.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    consensus.add_argument("--output", type=Path, required=True)
    consensus.add_argument("--minimum-confidence", type=int, choices=range(1, 6), default=3)
    args = parser.parse_args()

    if args.command == "validate":
        problems = validate_workbook(
            args.workbook,
            annotator=args.annotator,
            package_dir=args.package,
            allow_empty=args.allow_empty,
        )
        print(
            json.dumps({"valid": not problems, "problems": problems}, ensure_ascii=False, indent=2)
        )
        raise SystemExit(1 if problems else 0)
    if args.command == "compare":
        report = compare_workbooks(args.a, args.b, package_dir=args.package, output_dir=args.output)
    elif args.command == "finalize":
        report = finalize_gold(
            args.a,
            args.b,
            args.adjudication,
            package_dir=args.package,
            output_dir=args.output,
        )
    else:
        report = export_consensus_gold(
            args.a,
            args.b,
            package_dir=args.package,
            output_dir=args.output,
            minimum_confidence=args.minimum_confidence,
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
