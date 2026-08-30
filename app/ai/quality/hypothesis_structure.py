"""对候选假设做轻量、可复算的去重和互补维度标注。"""
from __future__ import annotations
import re

_LEVELS = {
    "需求/行业维度": ("需求", "行业", "政策", "补贴", "市场"),
    "竞争力/执行维度": ("销量", "订单", "交付", "出口", "渠道", "产能", "产品", "竞争"),
    "财务结果维度": ("收入", "利润", "毛利率", "现金流", "回报", "估值", "收入质量"),
}

def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]+", text))

def classify_level(statement: str) -> str:
    # 这是互补维度而非强制因果链：结果变量优先归入财务结果维度，
    # 其余按研究对象归入需求/行业或竞争力/执行维度。
    result_words = _LEVELS["财务结果维度"]
    causal_verbs = ("改善", "带动", "导致", "支撑", "提升", "增加", "降低")
    if any(word in statement for word in result_words) and any(word in statement for word in causal_verbs):
        return "财务结果维度"
    if any(word in statement for word in _LEVELS["需求/行业维度"]) and not any(word in statement for word in ("销量", "订单", "交付", "出口")):
        return "需求/行业维度"
    scores = {level: sum(word in statement for word in cues) for level, cues in _LEVELS.items()}
    return max(scores, key=scores.get) if max(scores.values(), default=0) else "待确认"

def inspect_hypotheses(hypotheses: list[dict]) -> list[dict]:
    seen: list[set[str]] = []
    for item in hypotheses:
        statement = str(item.get("statement") or "")
        tokens = _tokens(statement)
        duplicate = next((idx + 1 for idx, prior in enumerate(seen) if tokens and prior and len(tokens & prior) / len(tokens | prior) >= 0.6), None)
        item["logic_dimension"] = classify_level(statement)
        item["causal_level"] = item["logic_dimension"]  # 兼容已发布的草稿契约
        item["quality_warning"] = (f"与 H{duplicate} 高度重叠，建议合并或改写为不同因果环节" if duplicate else "")
        seen.append(tokens)
    return hypotheses
