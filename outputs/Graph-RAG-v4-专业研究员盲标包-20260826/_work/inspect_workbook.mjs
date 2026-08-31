import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const root = "E:/product/AI-Investment-Copilot/outputs/Graph-RAG-v4-专业研究员盲标包-20260826";
const inputPath = path.join(root, "v4_专业研究员独立盲标工作簿.xlsx");
const outputDir = path.join(root, "_work", "input-preview");
await fs.mkdir(outputDir, { recursive: true });

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
const summary = await workbook.inspect({
  kind: "workbook,sheet,table",
  maxChars: 12000,
  tableMaxRows: 8,
  tableMaxCols: 18,
  tableMaxCellChars: 120,
});
console.log(summary.ndjson);

const previews = [
  ["v4盲标", "A1:R12", "01_v4盲标_首屏.png"],
  ["质检概览", "A1:H16", "02_质检概览.png"],
  ["标注说明", "A1:H24", "03_标注说明.png"],
];
for (const [sheetName, range, filename] of previews) {
  const blob = await workbook.render({ sheetName, range, scale: 1, format: "png" });
  await fs.writeFile(path.join(outputDir, filename), new Uint8Array(await blob.arrayBuffer()));
}

const data = workbook.worksheets.getItem("v4盲标");
console.log(JSON.stringify({
  firstRows: data.getRange("A1:R5").values,
  formulas: data.getRange("A1:R5").formulas,
}, null, 2));
