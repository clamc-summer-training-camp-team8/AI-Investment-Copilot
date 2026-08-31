"""可见性过滤（PRD 12.1 / FR-A-001）。

三条规则，每条都有对应的攻击面：

1. **卡片按私有 / 团队 / 授权范围可见。** 越权检索会泄露他人研究方向。
2. **证据可见性不得高于来源文档。** 否则通过证据摘要可以读到无权限文档的内容。
3. **管理权限不等于内容访问权。** 管理员能配置系统，不代表能看全部研究内容。

这一层必须在 `app/services` 完成。`app/api` 不允许 import `app/db`
（`.importlinter` 强制），就是为了保证所有查询都经过这里。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.enums import Visibility
from app.services.errors import NotVisible

# 文档权限标签的敏感度排序。数字越大越敏感。
_LABEL_RANK: dict[str, int] = {"公开": 0, "内部": 1, "内部受限": 2, "机密": 3}

_VISIBILITY_RANK: dict[Visibility, int] = {
    Visibility.AUTHORIZED: 0,
    Visibility.TEAM: 1,
    Visibility.PRIVATE: 2,
}


@dataclass(frozen=True)
class Actor:
    """操作者。

    `is_admin` 只授予系统配置权限，不放宽内容可见性——这是 PRD 12.1 明确要求的
    分离。想让某人看全部内容，把他加进对应团队或授权范围，不要给管理员权限。
    """

    user_id: str
    teams: frozenset[str] = field(default_factory=frozenset)
    is_admin: bool = False
    document_labels: frozenset[str] = field(default_factory=lambda: frozenset({"公开", "内部"}))


def can_view_thesis(
    actor: Actor,
    *,
    owner: str,
    visibility: str,
    team: str | None = None,
    authorized_users: frozenset[str] | None = None,
) -> bool:
    """判断可见性。

    未识别的 `visibility` 取值按不可见处理，不按可见。数据写坏或新增枚举值时，
    默认全开会静默泄露；默认关闭只会让人来报「看不到」，后者可修，前者查不出来。
    """
    if owner == actor.user_id:
        return True
    if visibility == Visibility.PRIVATE:
        return False
    if visibility == Visibility.TEAM:
        return team is not None and team in actor.teams
    if visibility == Visibility.AUTHORIZED:
        # 授权范围为空表示还没授权给任何人，不等于对所有人开放
        return authorized_users is not None and actor.user_id in authorized_users
    return False


def ensure_thesis_visible(
    actor: Actor,
    *,
    thesis_id: str,
    owner: str,
    visibility: str,
    team: str | None = None,
    authorized_users: frozenset[str] | None = None,
) -> None:
    """不可见时抛 NotVisible，由 api 映射为 404。

    不抛 403：403 会确认对象存在，配合 ID 枚举可以还原他人的研究覆盖范围。
    """
    if not can_view_thesis(
        actor,
        owner=owner,
        visibility=visibility,
        team=team,
        authorized_users=authorized_users,
    ):
        raise NotVisible(f"逻辑 {thesis_id} 不存在或无访问权限")


def can_read_document(actor: Actor, *, visibility_label: str) -> bool:
    return visibility_label in actor.document_labels


def ensure_evidence_not_wider_than_document(
    *, evidence_visibility: str, document_label: str
) -> None:
    """证据可见性不得高于来源文档。

    比较方式：把文档标签的敏感度与卡片可见性的开放度对齐。文档越敏感、要求证据
    可见范围越窄。`内部受限` 及以上的文档，证据不允许设为 `授权`（最开放）。
    """
    doc_rank = _LABEL_RANK.get(document_label, max(_LABEL_RANK.values()))
    try:
        vis = Visibility(evidence_visibility)
    except ValueError as exc:
        raise NotVisible(f"未知的可见性取值 {evidence_visibility!r}") from exc

    if doc_rank >= _LABEL_RANK["内部受限"] and _VISIBILITY_RANK[vis] == 0:
        raise NotVisible(f"来源文档为 {document_label}，证据可见性不得设为 {evidence_visibility}")


def visible_filter(actor: Actor) -> dict[str, object]:
    """给仓储用的过滤条件。仓储不做权限判断，只接受这里算好的条件。"""
    return {
        "actor_id": actor.user_id,
        "teams": tuple(sorted(actor.teams)),
        "labels": tuple(sorted(actor.document_labels)),
    }
