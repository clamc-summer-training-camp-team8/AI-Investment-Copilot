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
                    problems.append(f"{spec['sheet']}!{row_number} {key}: fixed field changed: {field}")
            if allow_empty and not any(row.get(field, "") for field in required):
                continue
            for field in required:
                if not row.get(field, "").strip():
                    problems.append(f"{spec['sheet']}!{row_number} {key}: required blank: {field}")
            for field, values in contract["enums"].items():
                if field in row and row[field] and row[field] not in {str(value) for value in values}:
                    problems.append(f"{spec['sheet']}!{row_number} {key}: invalid {field}={row[field]}")

            timestamp = row.get("标注时间", "")
            if timestamp:
                try:
                    parsed = datetime.fromisoformat(timestamp)
                    if parsed.tzinfo is None:
                        raise ValueError
                except ValueError:
                    problems.append(f"{spec['sheet']}!{row_number} {key}: 标注时间 must be ISO 8601 with timezone")

            if task == "event":
                hypothesis = row.get("主要关联假设", "")
                direction = row.get("影响方向", "")
                if hypothesis == "无关" and direction != "无关":
                    problems.append(f"{spec['sheet']}!{row_number} {key}: 无关 hypothesis requires 无关 direction")
                if hypothesis in {"H1-需求与出货", "H2-盈利质量", "H3-产能与扩张"} and direction == "无关":
                    problems.append(f"{spec['sheet']}!{row_number} {key}: related hypothesis cannot use 无关 direction")
                if hypothesis.startswith("H") and not row.get("关键证据原文", "").strip():
                    problems.append(f"{spec['sheet']}!{row_number} {key}: related event requires evidence quote")
            elif task == "body_fact" and row.get("是否存在可抽取事实") == "是":
                for field in ("正文定位", "正文片段", "事实类型", "变化方向"):
                    if not row.get(field, "").strip():
                        problems.append(f"{spec['sheet']}!{row_number} {key}: extracted fact requires {field}")
            elif task == "graph_relevance":
                relevance = row.get("相关性等级", "")
                path_valid = row.get("关系路径可成立", "")
                if relevance == "0-无关" and path_valid == "是":
                    problems.append(f"{spec['sheet']}!{row_number} {key}: unrelated pair cannot have a valid path")
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
        raise ValueError(json.dumps({"A": a_problems, "B": b_problems}, ensure_ascii=False, indent=2))

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
                "agreement": round(sum(a == b for a, b in zip(left, right, strict=True)) / len(left), 4),
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
        writer = csv.DictWriter(stream, fieldnames=list(queue[0]) if queue else list(_empty_queue()))
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


def finalize_gold(
    a_path: Path,
    b_path: Path,
    adjudication_path: Path,
    *,
    package_dir: Path = DEFAULT_PACKAGE,
    output_dir: Path,
) -> dict[str, Any]:
    """Export frozen task CSVs after every comparison-queue row is adjudicated."""

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
        parsed_rulings[key] = {field: str(ruling[field]) for field in spec["core"]}

    output_dir.mkdir(parents=True, exist_ok=True)
    files: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
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
    }
    (output_dir / "final_gold_manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


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
    args = parser.parse_args()

    if args.command == "validate":
        problems = validate_workbook(
            args.workbook,
            annotator=args.annotator,
            package_dir=args.package,
            allow_empty=args.allow_empty,
        )
        print(json.dumps({"valid": not problems, "problems": problems}, ensure_ascii=False, indent=2))
        raise SystemExit(1 if problems else 0)
    if args.command == "compare":
        report = compare_workbooks(args.a, args.b, package_dir=args.package, output_dir=args.output)
    else:
        report = finalize_gold(
            args.a,
            args.b,
            args.adjudication,
            package_dir=args.package,
            output_dir=args.output,
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
