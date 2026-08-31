"""数据库约束守门测试。

这些约束是产品红线在存储层的最后一道兜底：即使业务代码有 bug，库也不接受
未来信息泄露和提前生成的窗口标签。用 PostgreSQL 跑，因为 CheckConstraint
与 timestamptz 的行为是被测对象本身。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.timeutil import BUSINESS_TZ
from app.db.models import Outcome, Security, Signal, Thesis

pytestmark = pytest.mark.integration


def _dt(day: str, hour: int = 9) -> datetime:
    return datetime.fromisoformat(day).replace(hour=hour, tzinfo=BUSINESS_TZ)


@pytest.fixture
def security(session: Session) -> Security:
    sec = Security(
        security_id="CONSTRAINT-DEMO001",
        name="华夏储能科技（虚拟）",
        is_illustrative=True,
    )
    session.add(sec)
    session.flush()
    return sec


def _signal(**overrides: object) -> Signal:
    defaults: dict[str, object] = {
        "signal_id": "SIG-TEST-001",
        "security_id": "CONSTRAINT-DEMO001",
        "name": "海外订单增长",
        "direction": "正向",
        "available_at": _dt("2026-02-10", 18),
        "generated_at": _dt("2026-02-10", 19),
        "model_version": "local-rule-v1",
        "prompt_version": "prompts-v1",
        "is_illustrative": True,
    }
    return Signal(**(defaults | overrides))


def test_信号生成时间早于可得时间被拒绝(session: Session, security: Security) -> None:
    """DQ-003：生成时间早于披露时间即未来数据泄露，库层直接拒绝。"""
    session.add(_signal(generated_at=_dt("2026-02-09", 10)))
    with pytest.raises(IntegrityError):
        session.flush()


def test_生成时间等于可得时间不算泄露(session: Session, security: Security) -> None:
    """边界：披露即生成是合法情形，不能一并拦掉。"""
    at = _dt("2026-02-10", 18)
    session.add(_signal(available_at=at, generated_at=at))
    session.flush()


def test_窗口标签不得早于窗口结束(session: Session, security: Security) -> None:
    """DQ-006：窗口标签只能在窗口结束后生成。"""
    session.add(_signal())
    session.flush()

    end = date(2026, 3, 10)
    session.add(
        Outcome(
            outcome_id="OUT-TEST-001",
            signal_id="SIG-TEST-001",
            security_id="CONSTRAINT-DEMO001",
            window_start_on=date(2026, 2, 11),
            window_end_on=end,
            label_generated_at=end - timedelta(days=1),
            is_illustrative=True,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_时间列往返保留时区(session: Session, security: Security) -> None:
    """timestamptz 列读回必须带时区，否则跨来源比较会退回 naive 混算。"""
    session.add(_signal())
    session.flush()
    session.expire_all()

    loaded = session.get(Signal, "SIG-TEST-001")
    assert loaded is not None
    assert loaded.generated_at.tzinfo is not None
    assert loaded.generated_at == _dt("2026-02-10", 19)


def test_同一公司不能持久化第二条投资逻辑(session: Session, security: Security) -> None:
    common = {
        "security_id": security.security_id,
        "direction": "观察",
        "core_view": "公司级逻辑只允许一条",
        "established_on": date(2026, 8, 26),
        "owner": "researcher",
        "visibility": "团队",
        "status": "草稿",
        "version": 0,
        "invalidation_require_all": True,
        "is_illustrative": True,
    }
    session.add(Thesis(thesis_id="THS-ONE", title="第一条", **common))
    session.flush()
    session.add(Thesis(thesis_id="THS-TWO", title="第二条", **common))

    with pytest.raises(IntegrityError):
        session.flush()
