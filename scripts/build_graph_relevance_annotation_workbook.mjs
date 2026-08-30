// Generic Graph-RAG v5+ researcher workbook builder. Configuration is provided
// through GRAPH_RAG_* environment variables by the versioned packaging script.
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

const artifactToolEntry = process.env.CODEX_ARTIFACT_TOOL_ENTRY || path.join(
  os.homedir(),
  ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs",
);
const { SpreadsheetFile, Workbook } = await import(pathToFileURL(artifactToolEntry).href);

const repoRoot = "E:/product/AI-Investment-Copilot";
const graphRagVersion = process.env.GRAPH_RAG_VERSION || "v5";
const packageDate = process.env.GRAPH_RAG_PACKAGE_DATE || "20260827";
const annotationSheetName = `${graphRagVersion}盲标`;
const sourceCsv = process.env.GRAPH_RAG_SOURCE_CSV
  || `${repoRoot}/outputs/graph-relevance-${graphRagVersion}-blind/researcher/annotation.csv`;
const outputDir = process.env.GRAPH_RAG_OUTPUT_DIR
  || `${repoRoot}/outputs/graph-rag-${graphRagVersion}-researcher-package-${packageDate}`;
const outputPath = `${outputDir}/Graph-RAG-${graphRagVersion}_专业研究员独立盲标工作簿.xlsx`;
const previewDir = process.env.GRAPH_RAG_PREVIEW_DIR
  || `${repoRoot}/.codex_tmp/${graphRagVersion}_annotation_workbook/previews`;

const csvText = await fs.readFile(sourceCsv, "utf8");
const workbook = await Workbook.fromCSV(csvText, { sheetName: annotationSheetName });
const annotation = workbook.worksheets.getItem(annotationSheetName);
const instructions = workbook.worksheets.add("标注说明");
const progress = workbook.worksheets.add("质检概览");

function toShanghaiWallClock(value) {
  const date = value instanceof Date ? value : new Date(String(value));
  if (Number.isNaN(date.getTime())) {
    throw new Error(`Invalid imported datetime: ${value}`);
  }
  return new Date(date.getTime() + 8 * 60 * 60 * 1000);
}

function sanitizeXmlText(value) {
  if (typeof value !== "string") {
    return value;
  }
  return value
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F\uFFFE\uFFFF]/g, "")
    .replace(/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/g, "�");
}

const queryRows = [];
const seenQueries = new Set();
const queryValues = annotation.getRange("C2:D301").values;
queryValues.forEach(([queryId, company], index) => {
  const normalizedQueryId = String(queryId ?? "");
  if (normalizedQueryId && !seenQueries.has(normalizedQueryId)) {
    seenQueries.add(normalizedQueryId);
    queryRows.push({
      queryId: normalizedQueryId,
      company: String(company ?? ""),
      sourceRow: index + 2,
    });
  }
});
if (queryRows.length !== 30) {
  throw new Error(`Expected 30 queries, found ${queryRows.length}`);
}

// CSV import provides robust quote/newline handling. Restore exact date display and
// force the five researcher-owned fields to be truly blank before delivery.
annotation.getRange("A1").values = [["关系样本ID"]];
annotation.getRange("A2:M301").values = annotation
  .getRange("A2:M301")
  .values.map((row) => row.map(sanitizeXmlText));
annotation.getRange("F2:F301").values = annotation
  .getRange("F2:F301")
  .values.map(([value]) => [toShanghaiWallClock(value)]);
annotation.getRange("J2:J301").values = annotation
  .getRange("J2:J301")
  .values.map(([value]) => [toShanghaiWallClock(value)]);
annotation.getRange("N2:R301").values = Array.from({ length: 300 }, () => [
  null,
  null,
  null,
  null,
  null,
]);

workbook.comments.setSelf({ displayName: "AI Investment Copilot" });

const navy = "#17324D";
const blue = "#2F6690";
const lightBlue = "#EAF2F8";
const paleYellow = "#FFF6D8";
const paleRed = "#FDECEC";
const paleGreen = "#E8F5E9";
const paleGray = "#F4F6F7";
const textColor = "#1F2937";
const subtleBorder = "#D6DEE6";

// Main register: A:M is frozen task material; N:R is the only editable area.
annotation.showGridLines = false;
annotation.freezePanes.freezeRows(1);
annotation.freezePanes.freezeColumns(3);
annotation.getRange("A1:R301").format = {
  font: { name: "Microsoft YaHei", size: 10, color: textColor },
  verticalAlignment: "top",
};
annotation.getRange("A1:R1").format = {
  fill: navy,
  font: { name: "Microsoft YaHei", size: 10, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
  rowHeight: 38,
  borders: { preset: "outside", style: "medium", color: navy },
};
annotation.getRange("A2:M301").format.fill = "#FFFFFF";
annotation.getRange("N2:R301").format.fill = paleYellow;
annotation.getRange("A2:R301").format.borders = {
  insideHorizontal: { style: "thin", color: subtleBorder },
};

const widths = {
  A: 23,
  B: 22,
  C: 12,
  D: 12,
  E: 11,
  F: 24,
  G: 42,
  H: 27,
  I: 44,
  J: 24,
  K: 45,
  L: 11,
  M: 70,
  N: 17,
  O: 17,
  P: 48,
  Q: 18,
  R: 28,
};
for (const [column, width] of Object.entries(widths)) {
  annotation.getRange(`${column}1:${column}301`).format.columnWidth = width;
}
for (const column of ["G", "I", "K", "M", "P"]) {
  annotation.getRange(`${column}2:${column}301`).format.wrapText = true;
}
annotation.getRange("A2:R301").format.rowHeight = 72;
for (const column of ["A", "B", "C", "E", "H", "K", "R"]) {
  annotation.getRange(`${column}1:${column}301`).format.numberFormat = "@";
}
annotation.getRange("F2:F301").format.numberFormat = "yyyy-mm-dd hh:mm:ss";
annotation.getRange("J2:J301").format.numberFormat = "yyyy-mm-dd hh:mm:ss";

annotation.getRange("N2:N301").dataValidation = {
  rule: { type: "list", values: ["0-无关", "1-弱相关", "2-间接相关", "3-直接相关"] },
};
annotation.getRange("O2:O301").dataValidation = {
  rule: { type: "list", values: ["是", "否"] },
};
for (const column of ["N", "O", "P", "Q", "R"]) {
  annotation.getRange(`${column}2:${column}301`).conditionalFormats.add("containsBlanks", {
    format: { fill: paleYellow },
  });
}
annotation.getRange("N2:N301").conditionalFormats.add("containsText", {
  text: "3-直接相关",
  format: { fill: "#D9EAD3", font: { color: "#216E39", bold: true } },
});
annotation.getRange("N2:N301").conditionalFormats.add("containsText", {
  text: "2-间接相关",
  format: { fill: "#DDEBF7", font: { color: "#1F4E78" } },
});
annotation.getRange("N2:N301").conditionalFormats.add("containsText", {
  text: "1-弱相关",
  format: { fill: "#FFF2CC", font: { color: "#7F6000" } },
});
annotation.getRange("N2:N301").conditionalFormats.add("containsText", {
  text: "0-无关",
  format: { fill: "#E7E6E6", font: { color: "#595959" } },
});
annotation.getRange("O2:O301").conditionalFormats.add("containsText", {
  text: "是",
  format: { fill: paleGreen, font: { color: "#216E39", bold: true } },
});
annotation.getRange("O2:O301").conditionalFormats.add("containsText", {
  text: "否",
  format: { fill: paleGray, font: { color: "#595959" } },
});

const annotationTable = annotation.tables.add(
  "A1:R301",
  true,
  `${graphRagVersion.toUpperCase()}AnnotationTable`,
);
annotationTable.style = "TableStyleMedium2";
annotationTable.showFilterButton = true;

workbook.comments.addThread(
  { cell: annotation.getRange("N1") },
  "必须从下拉列表选择：0-无关、1-弱相关、2-间接相关或3-直接相关。",
);
workbook.comments.addThread(
  { cell: annotation.getRange("P1") },
  "请写出可复核的判断依据，说明候选原文如何影响查询假设，不能只写‘相关’或‘无关’。",
);
workbook.comments.addThread(
  { cell: annotation.getRange("R1") },
  "请按 ISO 8601 且带时区填写，例如 2026-08-28T10:30:00+08:00。",
);

// Researcher instructions.
instructions.showGridLines = false;
instructions.mergeCells("A1:H2");
instructions.getRange("A1:H2").values = [[`Graph RAG ${graphRagVersion} 专业研究员独立盲标说明`]];
instructions.getRange("A1:H2").format = {
  fill: navy,
  font: { name: "Microsoft YaHei", size: 20, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "left",
  verticalAlignment: "center",
};
instructions.getRange("A4:H30").format.font = {
  name: "Microsoft YaHei",
  size: 10,
  color: textColor,
};
instructions.mergeCells("A4:H5");
instructions.getRange("A4:H5").values = [[
  "本工作簿包含 30 个全新查询、每个查询 10 个候选，共 300 行。每家公司采用相同的共享候选池，以避免通过候选集合反推相关性。题面与模型均已冻结；请独立阅读证据和原文后完成 N:R 五个黄色字段，禁止修改 A:M。",
]];
instructions.getRange("A4:H5").format = {
  fill: lightBlue,
  font: { name: "Microsoft YaHei", size: 11, color: textColor },
  wrapText: true,
  verticalAlignment: "center",
  borders: { preset: "outside", style: "thin", color: blue },
};

instructions.getRange("A7:B14").values = [
  ["数据版本", `graph-relevance-${graphRagVersion}-blind`],
  ["查询数", 30],
  ["每查询候选数", 10],
  ["候选关系数", 300],
  ["唯一候选文档数", 90],
  ["覆盖公司数", 9],
  ["检索截止时间", "2026-08-26 18:00:00（UTC+08:00）"],
  ["需要填写", "相关性等级、关系路径、理由、标注员、标注时间"],
];
instructions.getRange("A7:A14").format = {
  fill: "#DCE6F1",
  font: { bold: true, color: navy },
};
instructions.getRange("A7:B14").format.borders = {
  preset: "all",
  style: "thin",
  color: subtleBorder,
};

instructions.mergeCells("A16:H16");
instructions.getRange("A16:H16").values = [["相关性等级口径"]];
instructions.getRange("A16:H16").format = {
  fill: blue,
  font: { bold: true, color: "#FFFFFF", size: 12 },
};
instructions.getRange("A17:D21").values = [
  ["等级", "定义", "路径通常判断", "示例判断方式"],
  ["3-直接相关", "候选直接测量、披露或决定查询中的核心变量", "是", "销量表直接披露交付量；财报直接披露毛利率"],
  ["2-间接相关", "可通过一条清晰且有业务依据的因果链影响查询", "是", "产品获批可经商业化放量影响收入，但尚未披露销售"],
  ["1-弱相关", "主题相近，但缺少可靠或充分的传导链", "通常否", "同属该业务领域，但只披露程序性进展"],
  ["0-无关", "不能帮助判断查询，或仅为治理/证券程序事项", "否", "股东持股变化无法判断产品收入"],
];
instructions.getRange("A17:D17").format = {
  fill: navy,
  font: { bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
};
instructions.getRange("A17:D21").format.borders = {
  preset: "all",
  style: "thin",
  color: subtleBorder,
};
instructions.getRange("A17:D21").format.wrapText = true;

instructions.mergeCells("A23:H23");
instructions.getRange("A23:H23").values = [["填写与回收规则"]];
instructions.getRange("A23:H23").format = {
  fill: blue,
  font: { bold: true, color: "#FFFFFF", size: 12 },
};
instructions.getRange("A24:H30").values = [
  ["1", `只填写 ${annotationSheetName} 工作表的 N:R 黄色区域；A:M 是冻结题面，不得修改。`, null, null, null, null, null, null],
  ["2", "先阅读查询假设、公告标题和关键证据原文；有疑问时打开候选原文链接并核对页码。", null, null, null, null, null, null],
  ["3", "每行必须选择相关性等级和路径判断，并填写可复核的具体理由；即使多个查询共享同一候选，也要按当前查询独立判断。", null, null, null, null, null, null],
  ["4", "标注员填写稳定的研究员代号；标注时间使用带时区 ISO 8601，例如 2026-08-28T10:30:00+08:00。", null, null, null, null, null, null],
  ["5", "可以筛选和临时排序，但回传前不要删除、增加、合并或替换任何候选行。", null, null, null, null, null, null],
  ["6", "完成后查看 质检概览：完成数应为 300，剩余数和无效选项均应为 0，每个查询应完成 10 条。", null, null, null, null, null, null],
  ["7", "回传原始 XLSX 文件，不要复制到新表，也不要使用会改变字段名、公式或下拉选项的软件另存。", null, null, null, null, null, null],
];
for (let row = 24; row <= 30; row += 1) {
  instructions.mergeCells(`B${row}:H${row}`);
}
instructions.getRange("A24:A30").format = {
  fill: "#DCE6F1",
  font: { bold: true, color: navy },
  horizontalAlignment: "center",
};
instructions.getRange("B24:H30").format = {
  wrapText: true,
  verticalAlignment: "center",
};
instructions.getRange("A24:H30").format.borders = {
  preset: "all",
  style: "thin",
  color: subtleBorder,
};
instructions.getRange("A1:A30").format.columnWidth = 17;
instructions.getRange("B1:B30").format.columnWidth = 38;
instructions.getRange("C1:C30").format.columnWidth = 18;
instructions.getRange("D1:D30").format.columnWidth = 38;
instructions.getRange("E1:H30").format.columnWidth = 13;
instructions.getRange("A24:H30").format.rowHeight = 40;
instructions.freezePanes.freezeRows(2);

// Formula-driven completion and query-level QC.
progress.showGridLines = false;
progress.mergeCells("A1:F2");
progress.getRange("A1:F2").values = [[`${graphRagVersion} 盲标完成度与回收质检`]];
progress.getRange("A1:F2").format = {
  fill: navy,
  font: { name: "Microsoft YaHei", size: 18, bold: true, color: "#FFFFFF" },
  verticalAlignment: "center",
};
progress.getRange("A4:D48").format.font = {
  name: "Microsoft YaHei",
  size: 10,
  color: textColor,
};
progress.getRange("A4:B15").values = [
  ["检查项", "结果"],
  ["候选总数", 300],
  ["相关性等级已填", null],
  ["关系路径已填", null],
  ["标注理由已填", null],
  ["标注员已填", null],
  ["标注时间已填", null],
  ["五项全部完成", null],
  ["剩余未完成", null],
  ["完成率", null],
  ["无效相关性等级", null],
  ["无效路径选项", null],
];
progress.getRange("B6:B15").formulas = [
  [`=COUNTA('${annotationSheetName}'!N2:N301)`],
  [`=COUNTA('${annotationSheetName}'!O2:O301)`],
  [`=COUNTA('${annotationSheetName}'!P2:P301)`],
  [`=COUNTA('${annotationSheetName}'!Q2:Q301)`],
  [`=COUNTA('${annotationSheetName}'!R2:R301)`],
  [`=COUNTIFS('${annotationSheetName}'!N2:N301,\"<>\",'${annotationSheetName}'!O2:O301,\"<>\",'${annotationSheetName}'!P2:P301,\"<>\",'${annotationSheetName}'!Q2:Q301,\"<>\",'${annotationSheetName}'!R2:R301,\"<>\")`],
  ["=B5-B11"],
  ["=IFERROR(B11/B5,0)"],
  [`=B6-COUNTIF('${annotationSheetName}'!N2:N301,\"0-无关\")-COUNTIF('${annotationSheetName}'!N2:N301,\"1-弱相关\")-COUNTIF('${annotationSheetName}'!N2:N301,\"2-间接相关\")-COUNTIF('${annotationSheetName}'!N2:N301,\"3-直接相关\")`],
  [`=B7-COUNTIF('${annotationSheetName}'!O2:O301,\"是\")-COUNTIF('${annotationSheetName}'!O2:O301,\"否\")`],
];
progress.getRange("B13").format.numberFormat = "0.0%";
progress.getRange("A4:B4").format = {
  fill: blue,
  font: { bold: true, color: "#FFFFFF" },
};
progress.getRange("A5:A15").format = { fill: lightBlue, font: { bold: true, color: navy } };
progress.getRange("A4:B15").format.borders = {
  preset: "all",
  style: "thin",
  color: subtleBorder,
};
progress.getRange("B11").conditionalFormats.add("cellIs", {
  operator: "equal",
  formula: 300,
  format: { fill: paleGreen, font: { color: "#216E39", bold: true } },
});
progress.getRange("B12").conditionalFormats.add("cellIs", {
  operator: "greaterThan",
  formula: 0,
  format: { fill: paleRed, font: { color: "#9C0006", bold: true } },
});
progress.getRange("B14:B15").conditionalFormats.add("cellIs", {
  operator: "greaterThan",
  formula: 0,
  format: { fill: paleRed, font: { color: "#9C0006", bold: true } },
});

progress.getRange("A18:D48").values = [
  ["查询ID", "公司", "完成候选数", "状态"],
  ...queryRows.map(({ queryId, company }) => [queryId, company, null, null]),
];
queryRows.forEach(({ queryId }, index) => {
  const row = 19 + index;
  progress.getRange(`C${row}`).formulas = [[
    `=COUNTIFS('${annotationSheetName}'!C2:C301,"${queryId}",'${annotationSheetName}'!N2:N301,"<>",'${annotationSheetName}'!O2:O301,"<>",'${annotationSheetName}'!P2:P301,"<>",'${annotationSheetName}'!Q2:Q301,"<>",'${annotationSheetName}'!R2:R301,"<>")`,
  ]];
  progress.getRange(`D${row}`).formulas = [[
    `=IF(C${row}=10,"已完成",IF(C${row}=0,"未开始","进行中"))`,
  ]];
});
progress.getRange("A18:D18").format = {
  fill: blue,
  font: { bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
};
progress.getRange("A18:D48").format.borders = {
  preset: "all",
  style: "thin",
  color: subtleBorder,
};
progress.getRange("D19:D48").conditionalFormats.add("containsText", {
  text: "已完成",
  format: { fill: paleGreen, font: { color: "#216E39", bold: true } },
});
progress.getRange("D19:D48").conditionalFormats.add("containsText", {
  text: "进行中",
  format: { fill: paleYellow, font: { color: "#7F6000", bold: true } },
});
progress.getRange("D19:D48").conditionalFormats.add("containsText", {
  text: "未开始",
  format: { fill: paleGray, font: { color: "#595959" } },
});
progress.getRange("A1:A48").format.columnWidth = 23;
progress.getRange("B1:B48").format.columnWidth = 18;
progress.getRange("C1:C48").format.columnWidth = 18;
progress.getRange("D1:D48").format.columnWidth = 16;
progress.freezePanes.freezeRows(2);

await fs.mkdir(outputDir, { recursive: true });
await fs.mkdir(previewDir, { recursive: true });

const previewSpecs = [
  ["标注说明", "A1:H30", "instructions.png", 1.35],
  [annotationSheetName, "A1:R12", "annotation-top.png", 0.8],
  [annotationSheetName, "M294:R301", "annotation-bottom.png", 1.0],
  ["质检概览", "A1:F48", "quality.png", 1.2],
];
for (const [sheetName, range, fileName, scale] of previewSpecs) {
  const preview = await workbook.render({ sheetName, range, scale, format: "png" });
  await fs.writeFile(
    path.join(previewDir, fileName),
    new Uint8Array(await preview.arrayBuffer()),
  );
}

const inspectMain = await workbook.inspect({
  kind: "table",
  range: `${annotationSheetName}!A1:R8`,
  include: "values,formulas",
  tableMaxRows: 8,
  tableMaxCols: 18,
});
const inspectProgress = await workbook.inspect({
  kind: "table",
  range: "质检概览!A4:D22",
  include: "values,formulas",
  tableMaxRows: 20,
  tableMaxCols: 4,
});
const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
});

const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputPath);

console.log(JSON.stringify({
  outputPath,
  queryCount: queryRows.length,
  sheets: ["标注说明", annotationSheetName, "质检概览"],
  inspectMain: inspectMain.ndjson,
  inspectProgress: inspectProgress.ndjson,
  formulaErrors: formulaErrors.ndjson,
}, null, 2));
