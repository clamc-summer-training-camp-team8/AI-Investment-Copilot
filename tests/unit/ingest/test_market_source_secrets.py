from pathlib import Path

import pytest

from app.ingest.market_source_secrets import (
    read_tushare_credentials_file,
    read_tushare_token_file,
    sanitize_secret_text,
    validate_tushare_api_url,
)
from app.ingest.market_sources import MarketSourceError


@pytest.mark.parametrize(
    "content",
    [
        "TUSHARE_TOKEN=test-token-value-123456\n",
        "TOKEN:\ntest-token-value-123456\n",
        '{"token": "test-token-value-123456"}\n',
        "test-token-value-123456\n",
    ],
)
def test_读取常见Tushare密钥文件格式(tmp_path: Path, content: str) -> None:
    path = tmp_path / "tushare.txt"
    path.write_text(content, encoding="utf-8")
    assert read_tushare_token_file(path) == "test-token-value-123456"


def test_密钥文件错误不回显内容(tmp_path: Path) -> None:
    path = tmp_path / "tushare.txt"
    path.write_text("TOKEN=too-short\n", encoding="utf-8")
    with pytest.raises(MarketSourceError) as caught:
        read_tushare_token_file(path)
    assert "too-short" not in str(caught.value)


def test_异常文本脱敏显式及长Token() -> None:
    result = sanitize_secret_text(
        "Token: abcdefghijklmnopqrstuvwxyz123456 and known-value",
        secrets=("known-value",),
    )
    assert result == "Token: [REDACTED] and [REDACTED]"


def test_脱敏保留行情操作名便于定位() -> None:
    result = sanitize_secret_text(
        "tushare.daily_basic.2026-08-28 在 1 次尝试后失败",
    )
    assert result.startswith("tushare.daily_basic.2026-08-28")


def test_读取官方示例代码中的自定义API地址(tmp_path: Path) -> None:
    path = tmp_path / "tushare.py"
    path.write_text(
        "\n".join(
            (
                'token = "abcdefghijklmnopqrstuvwxyz1234567890"',
                "pro = ts.pro_api(token)",
                "pro._DataApi__token = token",
                "pro._DataApi__http_url = 'https://example.test'  # API Origin",
            )
        ),
        encoding="utf-8",
    )
    credentials = read_tushare_credentials_file(path)
    assert credentials.token == "abcdefghijklmnopqrstuvwxyz1234567890"
    assert credentials.api_url == "https://example.test"


def test_自定义API地址拒绝明文HTTP和路径() -> None:
    with pytest.raises(MarketSourceError, match="HTTPS Origin"):
        validate_tushare_api_url("http://example.test")
    with pytest.raises(MarketSourceError, match="HTTPS Origin"):
        validate_tushare_api_url("https://example.test/api")
