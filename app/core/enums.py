"""受控枚举。取值直接对应 PRD V1.2 与数据分析说明书 V1.0 的口径表，
不得随意增删：枚举变更会影响 JSON Schema 校验与历史数据可复算性。"""

from enum import StrEnum


class Direction(StrEnum):
    """投资逻辑方向。PRD 4.3 direction 字段。"""

    LONG = "看多"
    SHORT = "看空"
    WATCH = "观察"


class ThesisStatus(StrEnum):
    """PRD 5.2 状态机。'持续支持'不设为状态，仅作证据摘要展示。"""

    DRAFT = "草稿"
    VALIDATING = "验证中"
    DIVERGENT = "出现分歧"
    MAJOR_RISK = "重大风险"
    CLOSED = "已关闭"


class Visibility(StrEnum):
    PRIVATE = "私有"
    TEAM = "团队"
    AUTHORIZED = "授权"


class HypothesisType(StrEnum):
    INDUSTRY = "行业"
    COMPETITIVENESS = "公司竞争力"
    OPERATION = "经营"
    PROFITABILITY = "盈利"
    POLICY = "政策"
    VALUATION = "估值"
    OTHER = "其他"


class Importance(StrEnum):
    CORE = "核心"
    SUPPORTING = "辅助"


class HypothesisStatus(StrEnum):
    PENDING = "待验证"
    SUPPORTED = "支持"
    DIVERGENT = "分歧"
    AT_RISK = "风险"


class EvidenceType(StrEnum):
    FACT = "事实"
    EVENT = "事件"
    METRIC_CHANGE = "指标变化"
    MANAGEMENT_STATEMENT = "管理层表述"


class ImpactDirection(StrEnum):
    """证据/事件相对具体假设的影响方向。

    注意：这不是股价方向，也不是通用情绪极性。字段字典 FLD-007 明确要求区分。
    """

    SUPPORT = "支持"
    CONFLICT = "冲突"
    NEUTRAL = "中性"
    IRRELEVANT = "无关"


class SignalDirection(StrEnum):
    """AI 候选信号方向。字段字典 FLD-007 枚举，与 ImpactDirection 分开。"""

    POSITIVE = "正向"
    NEGATIVE = "负向"
    NEUTRAL = "中性"
    UNCERTAIN = "不确定"


class Strength(StrEnum):
    HIGH = "高"
    MEDIUM = "中"
    LOW = "低"


class Horizon(StrEnum):
    SHORT = "短期"
    MEDIUM = "中期"
    LONG = "长期"


class AiStatus(StrEnum):
    CANDIDATE = "候选"
    LOW_CONFIDENCE = "低置信"
    PARSE_FAILED = "解析失败"


class ConfirmationStatus(StrEnum):
    """人工确认闸门。只有 CONFIRMED 才进入正式证据链。"""

    PENDING = "待确认"
    CONFIRMED = "已确认"
    REJECTED = "已驳回"
    DEACTIVATED = "已解除"


class ReviewStatus(StrEnum):
    """人工复核结论。样例标注规范 Table 6 review_status 口径。"""

    PENDING = "待复核"
    PASSED = "通过"
    MODIFIED = "修改"
    REJECTED = "拒绝"


class MetricRole(StrEnum):
    LEADING = "领先"
    CONCURRENT = "同步"
    LAGGING = "滞后"


class ExpectationDirection(StrEnum):
    RISING = "上升"
    FALLING = "下降"
    FLUCTUATING = "波动"
    HIGHER_BETTER = "越高越好"
    LOWER_BETTER = "越低越好"
    NOT_BELOW_THRESHOLD = "不低于阈值"
    NOT_ABOVE_THRESHOLD = "不高于阈值"


class OutcomeState(StrEnum):
    OBSERVING = "待观察"
    COMPLETED = "已完成"


class FundamentalRealization(StrEnum):
    YES = "是"
    PARTIAL = "部分"
    NO = "否"
    OBSERVING = "待观察"


class Severity(StrEnum):
    """数据质量规则严重级别。BLOCKING 级失败不得进入正式信号和评测集。"""

    BLOCKING = "阻断"
    WARNING = "警告"
    INFO = "提示"


class ValidationVerdict(StrEnum):
    """确定性计算给出的规则结论。"""

    SUPPORT = "支持"
    CONFLICT = "冲突"
    PARTIAL_CONFLICT = "部分冲突"
    INSUFFICIENT = "信息不足"


class PeriodType(StrEnum):
    """报告期口径。指标管道要求：单季度/累计/年度/滚动不允许混算。"""

    SINGLE_QUARTER = "单季度"
    CUMULATIVE = "累计"
    ANNUAL = "年度"
    TRAILING = "滚动"
