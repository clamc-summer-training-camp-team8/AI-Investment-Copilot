import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const root = "E:/product/AI-Investment-Copilot/outputs/gold-annotation-v3-20260826";
const queuePath = path.join(root, "comparison", "adjudication_queue.csv");
const rulingsPath = path.join(root, "_work", "rulings.json");
const contractPath = path.join(root, "gold_contract_v3.json");
const templatePath = path.join(root, "04_裁决员_分歧裁决工作簿_v3.xlsx");
const csvOutputPath = path.join(root, "comparison", "adjudication_queue_completed.csv");
const xlsxOutputPath = path.join(root, "04_裁决员_分歧裁决工作簿_v3_已完成.xlsx");
const previewDir = path.join(root, "_work", "completed-workbook-preview");

const coreFields = {
  event: ["事件类别", "主要关联假设", "影响方向", "影响强度", "直接性"],
  body_fact: ["是否存在可抽取事实", "事实类型", "变化方向", "数值下限", "数值上限", "单位", "事实发生期"],
  graph_relevance: ["相关性等级", "关系路径可成立"],
};

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') {
        field += '"';
        i += 1;
      } else if (ch === '"') {
        quoted = false;
      } else {
        field += ch;
      }
    } else if (ch === '"') {
      quoted = true;
    } else if (ch === ",") {
      row.push(field);
      field = "";
    } else if (ch === "\n") {
      row.push(field.replace(/\r$/, ""));
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += ch;
    }
  }
  if (field.length || row.length) {
    row.push(field.replace(/\r$/, ""));
    rows.push(row);
  }
  return rows;
}

function encodeCsv(rows) {
  const quote = (value) => {
    const text = value == null ? "" : String(value);
    return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
  };
  return rows.map((row) => row.map(quote).join(",")).join("\r\n") + "\r\n";
}

function shanghaiTimestamp() {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Shanghai",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
    }).formatToParts(new Date()).filter((part) => part.type !== "literal").map((part) => [part.type, part.value]),
  );
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}+08:00`;
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const rawQueue = (await fs.readFile(queuePath, "utf8")).replace(/^\uFEFF/, "");
const queueMatrix = parseCsv(rawQueue);
const headers = queueMatrix[0];
const queueRows = queueMatrix.slice(1).filter((row) => row.some((value) => value !== ""));
const rulings = JSON.parse(await fs.readFile(rulingsPath, "utf8"));
const contract = JSON.parse(await fs.readFile(contractPath, "utf8"));
const headerIndex = Object.fromEntries(headers.map((header, index) => [header, index]));
const timestamp = shanghaiTimestamp();
const adjudicatorId = "ADJ-CODEX-FIN-01";

assert(queueRows.length === 161, `expected 161 queue rows, got ${queueRows.length}`);
assert(Object.keys(rulings).length === 161, `expected 161 rulings, got ${Object.keys(rulings).length}`);

const seen = new Set();
const taskCounts = { event: 0, body_fact: 0, graph_relevance: 0 };
const sourceCounts = { A: 0, B: 0, synthesis: 0 };
const completedRows = [];
for (const row of queueRows) {
  const task = row[headerIndex["任务类型"]];
  const sampleId = row[headerIndex["样本ID"]];
  const key = `${task}|${sampleId}`;
  assert(!seen.has(key), `duplicate queue key: ${key}`);
  seen.add(key);
  assert(rulings[key], `missing ruling: ${key}`);
  assert(coreFields[task], `unknown task: ${task}`);
  taskCounts[task] += 1;

  const expectedFields = coreFields[task];
  const result = rulings[key].result;
  assert(JSON.stringify(Object.keys(result).sort()) === JSON.stringify([...expectedFields].sort()), `${key}: incorrect result keys`);
  assert(String(rulings[key].reason || "").trim().length >= 12, `${key}: reason is too short`);

  for (const field of expectedFields) {
    const value = String(result[field] ?? "");
    if (contract.enums[field]) {
      assert(contract.enums[field].map(String).includes(value), `${key}: invalid enum ${field}=${value}`);
    }
  }

  if (task === "event") {
    if (result["主要关联假设"] === "无关") {
      assert(result["影响方向"] === "无关" && result["影响强度"] === "不适用" && result["直接性"] === "不适用", `${key}: unrelated event consistency`);
    }
    if (result["主要关联假设"] === "信息不足") {
      assert(result["影响方向"] === "信息不足" && result["影响强度"] === "不适用" && result["直接性"] === "不适用", `${key}: insufficient event consistency`);
    }
  } else if (task === "graph_relevance") {
    if (result["相关性等级"] === "0-无关") assert(result["关系路径可成立"] === "否", `${key}: graph 0 must be no-path`);
    if (result["相关性等级"] === "9-信息不足") assert(result["关系路径可成立"] === "信息不足", `${key}: graph 9 must be insufficient-path`);
  } else {
    const exists = result["是否存在可抽取事实"];
    if (exists === "是") {
      assert(result["事实类型"] !== "不适用" && result["变化方向"] !== "不适用", `${key}: extractable fact needs type and direction`);
      assert(String(result["事实发生期"]).trim() !== "", `${key}: extractable fact needs period`);
      for (const field of ["数值下限", "数值上限"]) {
        assert(String(result[field]).trim() !== "" && Number.isFinite(Number(result[field])), `${key}: ${field} must be numeric`);
      }
    } else if (exists === "否") {
      assert(result["事实类型"] === "不适用" && result["变化方向"] === "不适用", `${key}: no-fact consistency`);
      for (const field of ["数值下限", "数值上限", "单位", "事实发生期"]) assert(String(result[field]) === "", `${key}: no-fact fields must be blank`);
    }
  }

  const ordered = Object.fromEntries(expectedFields.map((field) => [field, result[field]]));
  const serialized = JSON.stringify(ordered);
  const aResult = JSON.stringify(JSON.parse(row[headerIndex["A结果"]]));
  const bResult = JSON.stringify(JSON.parse(row[headerIndex["B结果"]]));
  const canonical = JSON.stringify(Object.fromEntries(Object.entries(ordered).sort(([a], [b]) => a.localeCompare(b, "zh-CN"))));
  const aCanonical = JSON.stringify(Object.fromEntries(Object.entries(JSON.parse(aResult)).sort(([a], [b]) => a.localeCompare(b, "zh-CN"))));
  const bCanonical = JSON.stringify(Object.fromEntries(Object.entries(JSON.parse(bResult)).sort(([a], [b]) => a.localeCompare(b, "zh-CN"))));
  sourceCounts[canonical === aCanonical ? "A" : canonical === bCanonical ? "B" : "synthesis"] += 1;

  const completed = [...row];
  completed[headerIndex["裁决结果"]] = serialized;
  completed[headerIndex["裁决理由"]] = rulings[key].reason;
  completed[headerIndex["裁决人ID"]] = adjudicatorId;
  completed[headerIndex["裁决时间"]] = timestamp;
  completedRows.push(completed);
}

assert(Object.keys(rulings).every((key) => seen.has(key)), "rulings contain keys outside queue");
await fs.writeFile(csvOutputPath, "\uFEFF" + encodeCsv([headers, ...completedRows]), "utf8");

const input = await FileBlob.load(templatePath);
const workbook = await SpreadsheetFile.importXlsx(input);
const sheet = workbook.worksheets.getItem("分歧裁决队列");
assert(sheet, "template sheet 分歧裁决队列 not found");

const endRow = completedRows.length + 1;
sheet.getRange(`A2:J${endRow}`).values = completedRows;
sheet.freezePanes.freezeRows(1);
sheet.showGridLines = false;

const headerRange = sheet.getRange("A1:J1");
headerRange.format = {
  fill: "#173B63",
  font: { bold: true, color: "#FFFFFF", size: 11 },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
  rowHeightPx: 30,
};
const baseRange = sheet.getRange(`A2:F${endRow}`);
baseRange.format = {
  fill: "#F3F5F7",
  font: { color: "#222222", size: 10 },
  verticalAlignment: "top",
  wrapText: true,
  rowHeightPx: 66,
};
const rulingRange = sheet.getRange(`G2:J${endRow}`);
rulingRange.format = {
  fill: "#FFF2CC",
  font: { color: "#1F1F1F", size: 10 },
  verticalAlignment: "top",
  wrapText: true,
  rowHeightPx: 66,
};
sheet.getRange(`J2:J${endRow}`).setNumberFormat('yyyy-mm-dd"T"hh:mm:ss"+08:00"');
sheet.getRange(`A2:B${endRow}`).format.horizontalAlignment = "left";
sheet.getRange(`I2:J${endRow}`).format.horizontalAlignment = "center";
sheet.getRange(`A1:J${endRow}`).format.borders = {
  top: { color: "#D6DEE8", style: "continuous", weight: 1 },
  bottom: { color: "#D6DEE8", style: "continuous", weight: 1 },
  left: { color: "#D6DEE8", style: "continuous", weight: 1 },
  right: { color: "#D6DEE8", style: "continuous", weight: 1 },
  insideHorizontal: { color: "#D6DEE8", style: "continuous", weight: 1 },
  insideVertical: { color: "#D6DEE8", style: "continuous", weight: 1 },
};

const widths = [95, 105, 305, 360, 305, 360, 340, 430, 140, 190];
for (let column = 0; column < widths.length; column += 1) {
  sheet.getRangeByIndexes(0, column, endRow, 1).format.columnWidthPx = widths[column];
}

await fs.mkdir(previewDir, { recursive: true });
const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(xlsxOutputPath);

const previews = [
  ["分歧裁决队列", "A1:J12", "01_分歧裁决_首屏.png"],
  ["分歧裁决队列", `A${Math.max(2, endRow - 6)}:J${endRow}`, "02_分歧裁决_尾部.png"],
  ["枚举字典", "A1:L10", "03_枚举字典.png"],
  ["使用说明", "A1:H12", "04_使用说明.png"],
];
for (const [sheetName, range, filename] of previews) {
  const preview = await workbook.render({ sheetName, range, scale: 1, format: "png" });
  await fs.writeFile(path.join(previewDir, filename), new Uint8Array(await preview.arrayBuffer()));
}

console.log(JSON.stringify({
  queueRows: queueRows.length,
  taskCounts,
  sourceCounts,
  adjudicatorId,
  timestamp,
  csvOutputPath,
  xlsxOutputPath,
  previewDir,
}, null, 2));
