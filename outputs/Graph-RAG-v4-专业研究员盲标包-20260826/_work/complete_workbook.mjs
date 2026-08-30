import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";
import { rulings } from "./rulings.mjs";

const root = "E:/product/AI-Investment-Copilot/outputs/Graph-RAG-v4-专业研究员盲标包-20260826";
const inputPath = path.join(root, "v4_专业研究员独立盲标工作簿.xlsx");
const outputPath = path.join(root, "v4_专业研究员独立盲标工作簿_已完成.xlsx");
const previewDir = path.join(root, "_work", "output-preview");
const researcherId = "FIN-R01";

function shanghaiTimestamp() {
  const shifted = new Date(Date.now() + 8 * 60 * 60 * 1000);
  return shifted.toISOString().replace("Z", "+08:00");
}

function cleanText(value) {
  return String(value ?? "")
    .replace(/[\r\n\t]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function clip(value, maxLength) {
  const text = cleanText(value);
  return text.length <= maxLength ? text : `${text.slice(0, maxLength - 1)}…`;
}

function makeReason({ level, title, locator, evidence, hypothesis }) {
  const source = `《${clip(title, 34)}》${locator ? `（${clip(locator, 18)}）` : ""}`;
  const fact = clip(evidence, 78);
  const target = clip(hypothesis, 45);
  if (level === 3) {
    return `${source}直接披露“${fact}”，与“${target}”的核心变量或结果同口径，可直接用于判断，故判3级。`;
  }
  if (level === 2) {
    return `${source}披露“${fact}”，可建立公告事项到“${target}”的一阶业务传导链；但未直接给出最终结果，故判2级。`;
  }
  if (level === 1) {
    return `${source}仅披露“${fact}”，虽与公司经营或相邻主题有关，但不足以验证“${target}”的关键路径，故判1级。`;
  }
  return `${source}内容为“${fact}”，属于治理、证券程序或其他非核心事项，不能帮助判断“${target}”，故判0级。`;
}

function sha256(buffer) {
  return crypto.createHash("sha256").update(buffer).digest("hex");
}

await fs.mkdir(previewDir, { recursive: true });
const lockPaths = [path.join(root, "blind_manifest.json"), path.join(root, "model_lock.json")];
const lockHashesBefore = Object.fromEntries(
  await Promise.all(lockPaths.map(async (file) => [path.basename(file), sha256(await fs.readFile(file))])),
);

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
const annotation = workbook.worksheets.getItem("v4盲标");
const originalFrozen = annotation.getRange("A1:M241").values;
const rows = annotation.getRange("A2:M241").values;
if (rows.length !== 240) throw new Error(`工作簿数据行数异常：${rows.length}`);

const timestamp = shanghaiTimestamp();
const timestampCellValue = new Date(Date.now() + 8 * 60 * 60 * 1000);
const seen = new Set();
const outputValues = rows.map((row, rowIndex) => {
  const relationId = cleanText(row[0]);
  const ruling = rulings.get(relationId);
  if (!ruling) throw new Error(`第${rowIndex + 2}行关系样本ID无裁决：${relationId}`);
  if (seen.has(relationId)) throw new Error(`关系样本ID重复：${relationId}`);
  seen.add(relationId);
  const reason = makeReason({
    level: ruling.level,
    title: row[8],
    locator: row[11],
    evidence: row[12],
    hypothesis: row[6],
  });
  return [ruling.levelName, ruling.path, reason, researcherId, timestampCellValue];
});

if (seen.size !== 240 || [...rulings.keys()].some((id) => !seen.has(id))) {
  throw new Error(`裁决覆盖不完整：工作簿匹配${seen.size}/240`);
}

annotation.getRange("N2:R241").values = outputValues;
annotation.getRange("R2:R241").format.numberFormat = 'yyyy-mm-dd"T"hh:mm:ss.000"+08:00"';

const blankCount = outputValues.flat().filter((value) => cleanText(value) === "").length;
if (blankCount !== 0) throw new Error(`N:R仍有${blankCount}个空值`);

const distribution = outputValues.reduce((result, row) => {
  result[row[0]] = (result[row[0]] ?? 0) + 1;
  return result;
}, {});

const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputPath);

const completed = await SpreadsheetFile.importXlsx(await FileBlob.load(outputPath));
const completedAnnotation = completed.worksheets.getItem("v4盲标");
const completedFrozen = completedAnnotation.getRange("A1:M241").values;
if (JSON.stringify(originalFrozen) !== JSON.stringify(completedFrozen)) {
  throw new Error("冻结列A:M在输出文件中发生变化");
}

const completedInput = completedAnnotation.getRange("N2:R241").values;
const invalidRows = completedInput.filter((row) => {
  const [levelName, pathValue, reason, researcher, markedAt] = row.map(cleanText);
  const validLevel = ["3-直接相关", "2-间接相关", "1-弱相关", "0-无关"].includes(levelName);
  const expectedPath = levelName.startsWith("3-") || levelName.startsWith("2-") ? "是" : "否";
  const validTimestamp = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?\+08:00$/.test(markedAt) ||
    (typeof row[4] === "number" && row[4] > 45000 && row[4] < 50000);
  return !validLevel || pathValue !== expectedPath || reason.length < 30 || researcher !== researcherId || !validTimestamp;
});
if (invalidRows.length !== 0) throw new Error(`输出回读发现${invalidRows.length}条无效标注`);

const errors = await completed.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
});
console.log(errors.ndjson);

const qc = completed.worksheets.getItem("质检概览");
const qcInspection = await completed.inspect({
  kind: "region",
  sheetId: "质检概览",
  range: "A1:F48",
  include: "values,formulas",
  tableMaxRows: 60,
  tableMaxCols: 8,
  maxChars: 18000,
});
console.log(qcInspection.ndjson);

const previews = [
  ["v4盲标", "A1:R12", "01_v4盲标_首屏.png"],
  ["v4盲标", "A233:R241", "02_v4盲标_末屏.png"],
  ["质检概览", "A1:F48", "03_质检概览.png"],
  ["标注说明", "A1:H29", "04_标注说明.png"],
];
for (const [sheetName, range, filename] of previews) {
  const blob = await completed.render({ sheetName, range, scale: 1, format: "png" });
  await fs.writeFile(path.join(previewDir, filename), new Uint8Array(await blob.arrayBuffer()));
}

const lockHashesAfter = Object.fromEntries(
  await Promise.all(lockPaths.map(async (file) => [path.basename(file), sha256(await fs.readFile(file))])),
);
if (JSON.stringify(lockHashesBefore) !== JSON.stringify(lockHashesAfter)) {
  throw new Error("盲标清单或模型锁定文件发生变化");
}

console.log(JSON.stringify({
  outputPath,
  rowCount: rows.length,
  completedFields: completedInput.length * 5,
  invalidRows: invalidRows.length,
  frozenColumnsUnchanged: true,
  lockFilesUnchanged: true,
  distribution,
  timestamp,
}, null, 2));
