"""模型网关与具体提供者共享的异常。"""

from __future__ import annotations


class ModelUnavailable(RuntimeError):
    """已配置的模型端点当前无法完成请求。"""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable
