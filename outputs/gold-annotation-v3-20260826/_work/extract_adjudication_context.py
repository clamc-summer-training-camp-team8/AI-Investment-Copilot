from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re
import sys
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "outputs" / "gold-annotation-v3-20260826"
A_PATH = PACKAGE / "annotator_A_completed_A_20260826.xlsx"
B_PATH = PACKAGE / "annotator_B_completed_B-CODEX-FIN-01_20260826.xlsx"
QUEUE_PATH = PACKAGE / "comparison" / "adjudication_queue.csv"

SPECS = {
    "event": {"sheet": "事件语义_120", "key": "样本ID"},
    "body_fact": {"sheet": "正文事实_60", "key": "正文样本ID"},
    "graph_relevance": {"sheet": "GraphRAG相关性_180", "key": "关系样本ID"},
}
NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkg": "http://schemas.openxmlformats.org/package/2006/relationships",
}
CELL_REF = re.compile(r"([A-Z]+)(\d+)")


def column_index(reference: str) -> int:
    match = CELL_REF.fullmatch(reference)
    if not match:
        raise ValueError(reference)
    value = 0
    for character in match.group(1):
        value = value * 26 + ord(character) - 64
    return value - 1


def read_xlsx_sheet(path: Path, sheet_name: str) -> list[dict[str, str]]:
    with ZipFile(path) as archive:
        strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            strings = ["".join(n.text or "" for n in item.findall(".//main:t", NS)) for item in root]
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_paths = {
            node.get("Id", ""): node.get("Target", "")
            for node in relationships.findall("pkg:Relationship", NS)
        }
        sheet_path = ""
        for sheet in workbook.findall("main:sheets/main:sheet", NS):
            if sheet.get("name") == sheet_name:
                target = rel_paths[sheet.get(f"{{{NS['rel']}}}id", "")].lstrip("/")
                sheet_path = target if target.startswith("xl/") else f"xl/{target}"
                break
        if not sheet_path:
            raise ValueError(f"missing worksheet: {sheet_name}")
        root = ET.fromstring(archive.read(sheet_path))
        matrix: list[list[str]] = []
        for row_node in root.findall(".//main:sheetData/main:row", NS):
            values: dict[int, str] = {}
            for cell in row_node.findall("main:c", NS):
                index = column_index(cell.get("r", ""))
                cell_type = cell.get("t")
                if cell_type == "inlineStr":
                    value = "".join(n.text or "" for n in cell.findall(".//main:t", NS))
                else:
                    value_node = cell.find("main:v", NS)
                    raw = value_node.text if value_node is not None and value_node.text else ""
                    value = strings[int(raw)] if cell_type == "s" and raw else raw
                values[index] = value
            if values:
                matrix.append([values.get(i, "") for i in range(max(values) + 1)])
        headers = matrix[0]
        return [
            {header: row[i] if i < len(row) else "" for i, header in enumerate(headers)}
            for row in matrix[1:]
            if any(row)
        ]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("task", choices=tuple(SPECS))
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    spec = SPECS[args.task]
    key_field = str(spec["key"])
    queue = [row for row in read_csv(QUEUE_PATH) if row["任务类型"] == args.task]
    a_rows = {row[key_field]: row for row in read_xlsx_sheet(A_PATH, str(spec["sheet"]))}
    b_rows = {row[key_field]: row for row in read_xlsx_sheet(B_PATH, str(spec["sheet"]))}

    if args.task == "event":
        context_fields = [
            "样本ID", "公司", "证券代码", "披露时间", "公告标题", "原文链接",
            "核心观点", "H1-需求与出货", "H2-盈利质量", "H3-产能与扩张",
        ]
        annotation_fields = [
            "事件摘要", "事件类别", "主要关联假设", "影响方向", "影响强度",
            "直接性", "关键证据原文", "判断理由", "置信度", "数据问题",
        ]
    elif args.task == "body_fact":
        context_fields = [
            "正文样本ID", "事件样本ID", "公司", "证券代码", "披露时间",
            "公告标题", "原文链接",
        ]
        annotation_fields = [
            "正文定位", "正文片段", "是否存在可抽取事实", "事实类型", "变化方向",
            "数值下限", "数值上限", "单位", "事实发生期", "判断理由", "置信度", "数据问题",
        ]
    else:
        context_fields = [
            "关系样本ID", "事件样本ID", "公司", "证券代码", "检索截止时间",
            "查询假设", "候选公告标题", "候选原文链接",
        ]
        annotation_fields = [
            "相关性等级", "关系路径可成立", "关键证据原文", "判断理由", "置信度", "数据问题",
        ]

    for index, queue_row in enumerate(queue[args.offset : args.offset + args.limit], args.offset + 1):
        sample_id = queue_row["样本ID"]
        a_row = a_rows[sample_id]
        b_row = b_rows[sample_id]
        record = {
            "index": index,
            "task": args.task,
            "sample_id": sample_id,
            "context": {field: a_row.get(field, "") for field in context_fields},
            "A": {field: a_row.get(field, "") for field in annotation_fields},
            "B": {field: b_row.get(field, "") for field in annotation_fields},
        }
        print(json.dumps(record, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
