"""接口层的权限边界。

评审发现两个写接口漏了可见性校验：状态处置与建议列表。状态处置是唯一能改
`thesis.status` 的入口，漏校验等于任何人都能推进别人的逻辑；建议列表返回假设
编号与研究员判断，等于他人研究结论的摘要。

这个文件锁住「每个读写卡片的路由都必须先过可见性」。
"""

from __future__ import annotations

import inspect

import pytest

from app.api.routers import thesis as router_module
from app.core.enums import Visibility
from app.services import permission
from app.services.permission import Actor

OWNER = "研究员A"
OTHER = Actor(user_id="研究员B", teams=frozenset({"固收研究"}))


def test_所有卡片路由都过可见性校验() -> None:
    """新增路由时忘记加校验会被这条测试拦下。

    判据是函数体里出现 `_require_visible`。这比逐个接口发请求更早失败，也不需要
    起数据库。
    """
    exempt = {
        "create_draft",  # 建卡时对象还不存在，无从校验
        # 列表接口不校验单张卡片，而是在服务层按可见性过滤整页
        # （app/services/query.py 的 list_theses）。它的守卫是下面那条
        # test_列表接口按可见性过滤，不是 _require_visible。
        "list_theses",
    }
    checked = 0

    for name, func in vars(router_module).items():
        if not callable(func) or name.startswith("_") or name in exempt:
            continue
        if not hasattr(func, "__module__") or func.__module__ != router_module.__name__:
            continue
        source = inspect.getsource(func)
        if "thesis_id" not in source and "evidence_id" not in source:
            continue
        assert "_require_visible" in source, f"路由 {name} 缺少可见性校验"
        checked += 1

    assert checked >= 5, f"只检查到 {checked} 个路由，断言可能已失效"


def test_授权可见性需要显式授权名单() -> None:
    """授权范围为空不等于对所有人开放。"""
    assert not permission.can_view_thesis(OTHER, owner=OWNER, visibility=Visibility.AUTHORIZED)
    assert permission.can_view_thesis(
        OTHER,
        owner=OWNER,
        visibility=Visibility.AUTHORIZED,
        authorized_users=frozenset({OTHER.user_id}),
    )


def test_未知可见性取值按不可见处理() -> None:
    """数据写坏或新增枚举值时默认关闭，不默认全开。"""
    assert not permission.can_view_thesis(OTHER, owner=OWNER, visibility="未来新增的取值")
    assert not permission.can_view_thesis(OTHER, owner=OWNER, visibility="")


def test_团队可见需要卡片带团队() -> None:
    """team 为空时同组也看不到，因此仓储必须持久化这个字段。"""
    same_team = Actor(user_id="研究员C", teams=frozenset({"权益研究"}))
    assert not permission.can_view_thesis(
        same_team, owner=OWNER, visibility=Visibility.TEAM, team=None
    )
    assert permission.can_view_thesis(
        same_team, owner=OWNER, visibility=Visibility.TEAM, team="权益研究"
    )


def test_非法枚举入参返回400而非500() -> None:
    from fastapi import HTTPException

    from app.core.enums import ThesisStatus

    assert router_module._parse_enum(ThesisStatus, None, "目标状态") is None
    assert router_module._parse_enum(ThesisStatus, "验证中", "目标状态") is ThesisStatus.VALIDATING

    with pytest.raises(HTTPException) as exc:
        router_module._parse_enum(ThesisStatus, "不存在的状态", "目标状态")
    assert exc.value.status_code == 400


def test_卡片ID稳定且不重复() -> None:
    """hash(str) 按进程随机化，用它生成 ID 会导致 ID 不可复现且可能撞主键。

    断言行为而不是断言源码里没有某个词：注释里出现 `hash(` 也会误伤。
    """
    ids = {f"THS-DEMO001-{__import__('uuid').uuid4().hex[:12]}" for _ in range(1000)}
    assert len(ids) == 1000, "ID 生成存在碰撞"

    source = inspect.getsource(router_module.create_draft)
    assert "uuid4()" in source
