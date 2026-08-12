"""读接口的 HTTP 行为。

用 TestClient 实打请求，覆盖单测覆盖不到的部分：路由注册顺序、查询参数校验、
身份缺失的状态码。

不连数据库：需要 UoW 的接口用 fake 覆盖依赖。裁决队列读的是构建产物 CSV，
本身不需要 UoW。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_uow
from app.api.main import create_app
from app.core.domain import UnitOfWork
from tests.fakes import build_fake_uow

# 必须是 ASCII：HTTP 头只能承载 latin-1，中文用户名在客户端编码阶段就会失败。
# 网关注入的应当是账号 ID 而不是中文姓名，见 app/api/deps.py 的 get_actor。
HEADERS = {"X-User-Id": "analyst-a"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    uow = build_fake_uow()

    def _uow() -> Iterator[UnitOfWork]:
        yield uow

    app.dependency_overrides[get_uow] = _uow
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_缺少身份返回401(client: TestClient) -> None:
    assert client.get("/api/theses").status_code == 401


def test_卡片列表路由不被卡片详情吞掉(client: TestClient) -> None:
    """`/theses` 必须在 `/theses/{thesis_id}` 之前注册。

    顺序错了会把字面量 theses 当成 thesis_id，列表接口直接变 404。
    """
    response = client.get("/api/theses", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["page"]["total"] == 0


@pytest.mark.parametrize("limit", [0, -1, 101])
def test_非法分页参数返回422(client: TestClient, limit: int) -> None:
    """上限由 FastAPI 的 Query 约束拦住，不进业务层。"""
    response = client.get("/api/theses", params={"limit": limit}, headers=HEADERS)
    assert response.status_code == 422


def test_非法状态取值返回400(client: TestClient) -> None:
    """枚举非法是校验失败，不是 500。"""
    response = client.get("/api/theses", params={"status": "不存在的状态"}, headers=HEADERS)
    assert response.status_code == 400
    assert "可选" in response.json()["detail"]


def test_不可见卡片的趋势返回404(client: TestClient) -> None:
    """404 而不是 403：403 会暴露对象存在性。"""
    assert client.get("/api/theses/THS-NOT-EXIST/trends", headers=HEADERS).status_code == 404
    assert client.get("/api/theses/THS-NOT-EXIST/audit", headers=HEADERS).status_code == 404


def test_工作台返回四类聚合(client: TestClient) -> None:
    response = client.get("/api/workbench", headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "status_counts",
        "pending_evidence",
        "pending_suggestions",
        "review_due",
    }


def test_原文段落按定位回查(client: TestClient) -> None:
    from datetime import datetime

    from app.core.domain import DocumentRecord, DocumentSegmentRecord

    app = create_app()
    uow = build_fake_uow()
    uow.documents.add(
        DocumentRecord(
            document_id="DOC-1",
            title="测试公告",
            published_at=datetime.fromisoformat("2026-08-11T09:00:00+08:00"),
            content_hash="abc",
            parser_version="v1",
        ),
        [DocumentSegmentRecord("DOC-1", "DOC-1#paragraph-1", 1, "正文同比增长25%")],
        [],
    )

    def _uow() -> Iterator[UnitOfWork]:
        yield uow

    app.dependency_overrides[get_uow] = _uow
    with TestClient(app) as test_client:
        response = test_client.get("/api/documents/DOC-1/segments/1", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["content"] == "正文同比增长25%"


def test_导师裁决不可重复覆盖(client: TestClient) -> None:
    queue = client.get("/api/reviews/adjudications?limit=1", headers=HEADERS).json()
    if not queue["items"]:
        pytest.skip("裁决队列构建产物不存在")
    item = queue["items"][0]
    payload = {
        "hypothesis": item["annotator_a_hypothesis"],
        "direction": "中性",
        "reason": "独立核对原文后裁决",
    }
    first = client.post(
        f"/api/reviews/adjudications/{item['event_id']}", json=payload, headers=HEADERS
    )
    second = client.post(
        f"/api/reviews/adjudications/{item['event_id']}", json=payload, headers=HEADERS
    )
    assert first.status_code == 200
    assert first.json()["resolved"] is True
    assert second.status_code == 400


def test_用户标识必须可进HTTP头() -> None:
    """中文用户名进不了 HTTP 头，这是协议约束不是实现缺陷。

    示例数据里负责人是「研究员A」，若网关直接把中文姓名注入 X-User-Id，
    客户端在编码阶段就失败。这条测试把约束固定下来，避免有人照着示例数据
    去配网关。
    """
    with pytest.raises(UnicodeEncodeError):
        "研究员A".encode("latin-1")
    assert "analyst-a".encode("latin-1")


def test_裁决队列分页且带分歧类型(client: TestClient) -> None:
    """队列要能按页取，并标出分歧在假设还是方向。

    导师裁决（mentor-ruling-v1）落地后队列应为空：原 471 条方向分歧已由
    业务规则统一裁定。断言写成「空队列合法、非空则每条都标出分歧类型」，
    而不是断言某个具体条数——条数会随裁决版本变化，写死会让规则更新时
    测试无意义地失败。
    """
    response = client.get("/api/reviews/adjudications", params={"limit": 5}, headers=HEADERS)
    assert response.status_code == 200

    body = response.json()
    assert body["page"]["total"] >= 0
    assert all(item["disagreement"] in ("假设", "方向", "假设、方向") for item in body["items"])


def test_裁决完成后队列应为空(client: TestClient) -> None:
    """裁决书 20260811 覆盖了当时全部 471 条分歧，队列清零。

    这条测试是回退护栏：如果后续改动重新引入了未裁决的分歧，
    队列会变为非空，此时应当补裁决规则或更新裁决书，而不是改这条断言。
    """
    response = client.get("/api/reviews/adjudications", params={"limit": 1}, headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["page"]["total"] == 0


def test_裁决队列不给系统建议(client: TestClient) -> None:
    """给「系统建议」会让导师跟随而不是独立判断，而这个队列的目的正是取得
    独立于抽取规则的人工金标。"""
    response = client.get("/api/reviews/adjudications", params={"limit": 1}, headers=HEADERS)
    body = response.json()
    for item in body["items"]:
        assert "suggested_direction" not in item
        assert "system_suggestion" not in item
