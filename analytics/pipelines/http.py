"""采集用的 HTTP 小工具：重试退避 + 分片缓存。

为什么需要这层：原来三个 fetch 脚本各自裸调 urlopen，没有任何 try/except，
且只在全部抓完后一次性写盘。扩到 9 家公司后请求量是原来的三倍，行情源实测
在连续请求下会直接 RemoteDisconnected，单点失败就把已抓的数据全部丢掉。

两个设计取舍：
- 退避是指数的，但**不无限重试**。抓不到就抛，让调用方知道数据不完整，
  而不是静默返回空结果——空结果会被下游当成「这家公司没有公告」。
- 缓存按分片落盘，重跑时默认复用。数据采集要可复算，同一天重跑不该因为
  上游翻页顺序变化而得到不同结果。要强制重抓用 refresh=True。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

DEFAULT_HEADERS = {"User-Agent": "Mozilla/5.0 (research-tooling; MVP validation)"}


class FetchError(RuntimeError):
    """重试用尽仍失败。带上尝试次数，方便报告里写清楚是网络问题还是数据问题。"""


def request_json(
    url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
    attempts: int = 5,
    backoff: float = 1.5,
    base_pause: float = 1.0,
) -> dict[str, Any]:
    """带指数退避的 JSON 请求。

    退避从 base_pause 起，每次乘 backoff。行情源限流后需要秒级以上的间隔，
    亚秒级重试只会继续撞墙。
    """
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(url, data=data, headers=headers or DEFAULT_HEADERS)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as exc:
            last = exc
            if attempt == attempts:
                break
            pause = base_pause * (backoff ** (attempt - 1))
            print(f"    重试 {attempt}/{attempts - 1}（{type(exc).__name__}），等 {pause:.1f}s")
            time.sleep(pause)
    raise FetchError(f"{attempts} 次尝试后仍失败: {url}") from last


def cached_shard(
    path: Path,
    build: Callable[[], Any],
    *,
    refresh: bool = False,
    label: str = "",
) -> Any:
    """分片缓存：已有分片直接读，否则调 build 抓取并落盘。

    分片粒度是「一家公司一个文件」。这样任何一家抓失败时，已成功的公司
    不需要重抓，而且能看出到底缺了谁。
    """
    if path.exists() and not refresh:
        print(f"  {label} 复用缓存 {path.name}")
        return json.loads(path.read_text(encoding="utf-8"))

    payload = build()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload
