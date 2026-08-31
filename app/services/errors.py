"""业务异常。

按 contracts/api/README.md 的错误码约定分类，`app/api` 负责映射到 HTTP 状态码。

特别注意 `NotVisible` 对应 **404 而不是 403**：403 会暴露对象存在性，可以通过
枚举 ID 探测他人的研究覆盖范围，而研究覆盖本身是敏感信息（PRD 12.1）。
"""

from __future__ import annotations


class ServiceError(Exception):
    """业务异常基类。"""


class ValidationFailed(ServiceError):
    """入参或业务前置条件不满足。→ 400"""


class NotVisible(ServiceError):
    """对象不存在，或调用者无权访问。→ 404（不区分，刻意如此）"""


class EntityAmbiguous(ServiceError):
    """证券实体歧义。→ 409，返回候选列表要求用户选择，不自动绑定（PRD 7.4）。"""

    def __init__(self, message: str, candidates: list[dict[str, str]]) -> None:
        super().__init__(message)
        self.candidates = candidates


class ThesisAlreadyExists(ServiceError):
    """同一公司已经有投资逻辑。→ 409

    ``thesis_id`` 只在调用者有权看到既有逻辑时返回；否则不能借冲突响应探测
    其他团队的研究覆盖。
    """

    def __init__(self, message: str, thesis_id: str | None = None) -> None:
        super().__init__(message)
        self.thesis_id = thesis_id


class HumanGateRequired(ServiceError):
    """试图绕过人工确认闸门。→ 400

    这个异常存在本身就是产品红线的实现：AI 产出一律为候选，正式状态变更必须由
    负责人确认并填原因（PRD 5.4 / FR-S-002）。
    """


class IllegalTransition(ServiceError):
    """状态流转不合法。→ 400"""


class CalibrationConflict(ServiceError):
    """指标口径冲突。→ 409，并列展示口径与来源，禁止直接比较（PRD 7.4）。"""
