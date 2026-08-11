"""模型网关与 Provider 共用的异常类型。"""

from __future__ import annotations


class ModelUnavailable(RuntimeError):
    """模型端点当前不能完成请求，并声明任务是否适合重试。"""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable
