const levelsByQuery = {
  Q001: [3, 0, 0, 0, 0, 0, 0, 0],
  Q002: [0, 0, 0, 0, 0, 1, 0, 0],
  Q003: [0, 0, 0, 0, 0, 1, 0, 0],
  Q004: [1, 1, 1, 1, 0, 3, 3, 0],
  Q005: [0, 3, 1, 3, 3, 1, 1, 1],
  Q006: [1, 1, 1, 3, 1, 1, 1, 0],
  Q007: [1, 2, 2, 0, 0, 1, 1, 1],
  Q008: [3, 3, 3, 3, 3, 1, 1, 0],
  Q009: [2, 2, 2, 0, 1, 1, 1, 0],
  Q010: [2, 2, 3, 1, 3, 1, 1, 0],
  Q011: [0, 1, 1, 1, 1, 2, 2, 0],
  Q012: [0, 2, 2, 2, 2, 3, 3, 0],
  Q013: [1, 1, 1, 1, 2, 3, 1, 0],
  Q014: [2, 0, 2, 2, 0, 3, 1, 2],
  Q015: [0, 0, 2, 3, 1, 1, 3, 0],
  Q016: [2, 1, 0, 3, 0, 3, 2, 1],
  Q017: [0, 0, 0, 0, 0, 1, 2, 0],
  Q018: [2, 2, 2, 2, 2, 1, 2, 0],
  Q019: [0, 0, 0, 0, 0, 3, 2, 0],
  Q020: [0, 0, 0, 0, 0, 1, 2, 0],
  Q021: [2, 0, 1, 0, 2, 3, 1, 0],
  Q022: [3, 0, 0, 0, 0, 3, 1, 3],
  Q023: [2, 1, 1, 1, 1, 3, 2, 0],
  Q024: [0, 0, 0, 1, 1, 2, 1, 0],
  Q025: [2, 0, 0, 0, 1, 3, 3, 0],
  Q026: [0, 2, 0, 0, 2, 2, 2, 0],
  Q027: [2, 0, 2, 0, 1, 2, 1, 0],
  Q028: [2, 2, 2, 2, 2, 1, 1, 0],
  Q029: [0, 0, 0, 0, 3, 2, 0, 0],
  Q030: [3, 3, 3, 3, 0, 1, 1, 0],
};

const levelNames = {
  0: "0-无关",
  1: "1-弱相关",
  2: "2-间接相关",
  3: "3-直接相关",
};

const rulings = new Map();
for (const [queryKey, levels] of Object.entries(levelsByQuery)) {
  if (levels.length !== 8) throw new Error(`${queryKey} 不含8个候选裁决`);
  for (let candidate = 1; candidate <= 8; candidate += 1) {
    const queryNumber = queryKey.slice(1);
    const candidateNumber = String(candidate).padStart(2, "0");
    const relationId = `V4-R-Q${queryNumber}-C${candidateNumber}`;
    const level = levels[candidate - 1];
    rulings.set(relationId, {
      level,
      levelName: levelNames[level],
      path: level >= 2 ? "是" : "否",
    });
  }
}

if (rulings.size !== 240) throw new Error(`裁决数量异常：${rulings.size}`);

export { rulings, levelNames };
