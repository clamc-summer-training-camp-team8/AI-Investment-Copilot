"""离线行情构建使用的本地密钥读取与脱敏工具。

密钥文件只能用于本地构建/权限探测；任何返回值都不得进入日志、冻结资产或异常文本。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from app.ingest.market_sources import MarketSourceError

_TOKEN_KEYS = {"token", "tusharetoken"}
# Tushare Token 是长字母数字串；点、下划线和连字符常见于可观测操作名，
# 不能把 `tushare.daily_basic.2026-08-28` 这类定位信息误删。
_LONG_SECRET = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9]{24,}(?![A-Za-z0-9])")
_LABELED_SECRET = re.compile(r"(?i)((?:tushare[_\s-]*)?token\s*[:=：])\s*[^\s,;]+")
_HTTPS_URL = re.compile(r"https://[^\s\"']+")


@dataclass(frozen=True)
class TushareCredentials:
    token: str
    api_url: str | None = None


def _normalized_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).strip().lower())


def _clean_candidate(value: object) -> str:
    return str(value).strip().strip("\"'")


def read_tushare_token_file(path: Path) -> str:
    """从常见本地配置格式读取 Token，不在错误中包含文件内容。"""

    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise MarketSourceError(f"无法读取 Tushare 密钥文件: {path}") from exc
    candidates: list[str] = []
    stripped = raw.strip()

    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise MarketSourceError("Tushare 密钥文件是无效 JSON") from exc
        if isinstance(payload, dict):
            candidates.extend(
                _clean_candidate(value)
                for key, value in payload.items()
                if _normalized_key(key) in _TOKEN_KEYS
            )
    else:
        waiting_for_token_value = False
        for line in raw.splitlines():
            value = line.strip()
            if not value or value.startswith(("#", ";")):
                continue
            if waiting_for_token_value:
                candidates.append(_clean_candidate(value))
                waiting_for_token_value = False
                continue
            match = re.match(r"^\s*([^:=：]+?)\s*[:=：]\s*(.*?)\s*$", value)
            if match and _normalized_key(match.group(1)) in _TOKEN_KEYS:
                candidate = _clean_candidate(match.group(2))
                if candidate:
                    candidates.append(candidate)
                else:
                    waiting_for_token_value = True
        meaningful = [
            line.strip()
            for line in raw.splitlines()
            if line.strip() and not line.lstrip().startswith(("#", ";"))
        ]
        if not candidates and len(meaningful) == 1 and not re.search(r"[:=：]", meaningful[0]):
            candidates.append(_clean_candidate(meaningful[0]))

    values = {candidate for candidate in candidates if candidate}
    if not values:
        raise MarketSourceError("Tushare 密钥文件中没有可识别的 Token")
    if len(values) != 1:
        raise MarketSourceError("Tushare 密钥文件中存在多个不同的 Token 候选值")
    token = values.pop()
    if len(token) < 16 or any(character.isspace() for character in token):
        raise MarketSourceError("Tushare Token 格式无效")
    return token


def validate_tushare_api_url(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise MarketSourceError(
            "Tushare 自定义 API 地址必须是无用户信息、查询参数和路径的 HTTPS Origin"
        )
    return normalized


def read_tushare_credentials_file(path: Path) -> TushareCredentials:
    """读取 Token 及代码示例中的可选兼容 API Origin。"""

    token = read_tushare_token_file(path)
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise MarketSourceError(f"无法读取 Tushare 密钥文件: {path}") from exc
    api_urls: set[str] = set()
    for line in raw.splitlines():
        value = line.strip()
        if not value or value.startswith(("#", ";")):
            continue
        left, separator, _ = value.partition("=")
        if not separator:
            continue
        normalized_key = _normalized_key(left)
        if not (
            normalized_key in {"apiurl", "tushareapiurl", "httpurl"}
            or normalized_key.endswith("dataapihttpurl")
        ):
            continue
        match = _HTTPS_URL.search(value)
        if match:
            api_urls.add(match.group(0))
    if len(api_urls) > 1:
        raise MarketSourceError("Tushare 密钥文件中存在多个不同的自定义 API 地址")
    api_url = validate_tushare_api_url(api_urls.pop() if api_urls else None)
    return TushareCredentials(token=token, api_url=api_url)


def sanitize_secret_text(value: object, *, secrets: tuple[str, ...] = ()) -> str:
    """清除异常中的显式 Token 和长凭证形态字符串。"""

    text = str(value)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = _LABELED_SECRET.sub(r"\1 [REDACTED]", text)
    return _LONG_SECRET.sub("[REDACTED]", text)
