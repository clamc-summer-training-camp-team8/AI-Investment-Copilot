from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.api.deps import get_settings, get_uow
from app.api.main import create_app
from app.core.config import Settings
from app.core.domain import SecurityRecord
from tests.fakes import build_fake_uow


@contextmanager
def _client(*, qa_enabled: bool = False) -> Iterator[TestClient]:
    uow = build_fake_uow()
    uow.securities.add(SecurityRecord(security_id="0175.HK", name="吉利汽车"))
    application = create_app()
    application.dependency_overrides[get_uow] = lambda: uow
    application.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        global_search_enabled=True,
        knowledge_qa_enabled=qa_enabled,
        knowledge_qa_graph_enabled=False,
    )
    try:
        with TestClient(application, headers={"X-User-Id": "analyst"}) as client:
            yield client
    finally:
        application.dependency_overrides.clear()


def test_search_route_is_registered() -> None:
    with _client() as client:
        response = client.get("/api/search", params={"q": "吉利"})
        assert response.status_code == 200
        assert response.json()["groups"][0]["items"][0]["title"] == "吉利汽车"


def test_assistant_feature_flag_is_independent_from_search() -> None:
    with _client(qa_enabled=False) as client:
        response = client.post("/api/assistant/answers", json={"question": "有哪些证据？"})
        assert response.status_code == 404
        assert client.get("/api/search", params={"q": "吉利"}).status_code == 200
