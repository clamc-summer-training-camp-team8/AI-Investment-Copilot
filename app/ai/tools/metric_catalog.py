"""周期指标目录工具。

该模块把 ``data/metric_catalog.json`` 装载到本地 SQLite。目录负责回答“哪些指标
能够稳定获得”，模型只负责在工具返回的候选集合中说明关联理由，避免自由生成不存在
的指标。默认使用内存数据库；传入 ``database_path`` 时可得到可复用的本地数据库。
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_DEFAULT_SEED_PATH = Path(__file__).resolve().parents[1] / "data" / "metric_catalog.json"
_GRADE_SCORE = {"A": 4, "B": 3, "C": 2, "D": 1}
_EXCHANGE_SUFFIX = re.compile(r"\.(?:SH|SZ|BJ|HK)$", re.IGNORECASE)


@dataclass(frozen=True)
class MetricCandidate:
    """提供给指标推荐 Agent 的受控候选项。"""

    metric_id: str
    metric_version: str
    metric_name: str
    definition: str
    unit: str
    frequency: str
    period_type: str
    expected_direction: str | None
    relation_type: str
    threshold_policy: str
    availability_grade: str
    observation_frequency: str
    polling_frequency: str
    source_ids: tuple[str, ...]
    availability_note: str
    matching_reasons: tuple[str, ...]
    retrieval_score: float

    def to_prompt_dict(self) -> dict[str, Any]:
        """转换为可序列化结构，供模型提示词和审计记录使用。"""
        payload = asdict(self)
        payload["source_ids"] = list(self.source_ids)
        payload["matching_reasons"] = list(self.matching_reasons)
        return payload


class MetricCatalogTool:
    """基于 SQLite 的九家公司周期指标检索工具。"""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._connection.row_factory = sqlite3.Row

    @classmethod
    def from_seed(
        cls,
        *,
        seed_path: str | Path | None = None,
        database_path: str | Path | None = None,
    ) -> MetricCatalogTool:
        """从版本化 JSON 初始化目录；重复初始化会覆盖旧目录，结果可复现。"""
        seed = Path(seed_path) if seed_path is not None else _DEFAULT_SEED_PATH
        content = json.loads(seed.read_text(encoding="utf-8"))
        if database_path is None:
            connection = sqlite3.connect(":memory:")
        else:
            target = Path(database_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(target)
        tool = cls(connection)
        tool._create_schema()
        tool._replace_seed(content)
        return tool

    @classmethod
    def from_snapshot(cls, content: dict[str, Any]) -> MetricCatalogTool:
        """从调用方提供的目录快照创建内存目录。

        生产服务可把 PostgreSQL 中当前证券的指标定义和可用性投影为这个
        与种子目录相同的契约；``app.ai`` 不需要依赖数据库驱动或 ORM。
        """
        connection = sqlite3.connect(":memory:")
        tool = cls(connection)
        tool._create_schema()
        tool._replace_seed(content)
        return tool

    @property
    def catalog_version(self) -> str:
        """返回当前目录版本，便于将推荐结果与目录快照绑定。"""
        row = self._connection.execute(
            "SELECT value FROM catalog_meta WHERE key = 'catalog_version'"
        ).fetchone()
        return str(row["value"]) if row else "unknown"

    def search(
        self,
        *,
        hypothesis: str,
        security_id: str | None = None,
        industry: str | None = None,
        top_k: int = 8,
    ) -> list[MetricCandidate]:
        """按公司、行业与业务关键词召回可周期获得的指标。

        公司专属可得性优先于通用可得性。没有业务关键词命中的指标不会仅因定义中偶然
        出现同一个汉字而入选；这样可以控制候选集噪声。
        """
        if top_k <= 0:
            return []
        normalized_security = _normalize_security_id(security_id)
        company = self.company_context(normalized_security) if normalized_security else None
        # 已登记公司的行业是目录事实，优先于调用方可能过期或误填的行业标签。
        effective_industry = str(company["industry"]) if company else industry
        rows = self._connection.execute("SELECT * FROM metric ORDER BY metric_id").fetchall()
        candidates: list[MetricCandidate] = []
        for row in rows:
            industries = tuple(json.loads(row["industries_json"]))
            if effective_industry and effective_industry not in industries:
                continue
            reasons, text_score = _matching_reasons(
                hypothesis,
                metric_name=str(row["name"]),
                keywords=tuple(json.loads(row["keywords_json"])),
            )
            if text_score <= 0:
                continue
            availability = self._availability_for(
                metric_id=str(row["metric_id"]), security_id=normalized_security
            )
            if not availability:
                continue
            grade = max(
                (str(item["availability_grade"]) for item in availability),
                key=lambda item: _GRADE_SCORE.get(item, 0),
            )
            exact_company = bool(
                normalized_security
                and any(str(item["security_id"]) == normalized_security for item in availability)
            )
            retrieval_score = (
                text_score
                + _GRADE_SCORE.get(grade, 0) * 2
                + (3 if exact_company else 0)
                + (1 if effective_industry else 0)
            )
            if exact_company:
                reasons.append("该公司存在专属且已核验的数据来源")
            reasons.append(f"可得性等级 {grade}")
            candidates.append(
                MetricCandidate(
                    metric_id=str(row["metric_id"]),
                    metric_version=str(row["version"]),
                    metric_name=str(row["name"]),
                    definition=str(row["definition"]),
                    unit=str(row["unit"]),
                    frequency=str(row["frequency"]),
                    period_type=str(row["period_type"]),
                    expected_direction=row["expected_direction"],
                    relation_type=str(row["relation_type"]),
                    threshold_policy=str(row["threshold_policy"]),
                    availability_grade=grade,
                    observation_frequency=_join_distinct(
                        str(item["observation_frequency"]) for item in availability
                    ),
                    polling_frequency=_join_distinct(
                        str(item["polling_frequency"]) for item in availability
                    ),
                    source_ids=tuple(sorted({str(item["source_id"]) for item in availability})),
                    availability_note=_join_distinct(str(item["note"]) for item in availability),
                    matching_reasons=tuple(reasons),
                    retrieval_score=float(retrieval_score),
                )
            )
        candidates.sort(key=lambda item: (-item.retrieval_score, item.metric_id))
        return candidates[:top_k]

    def company_context(self, security_id: str | None) -> dict[str, str] | None:
        """查询公司上下文；接受 ``002594`` 和 ``002594.SZ`` 两种代码。"""
        normalized = _normalize_security_id(security_id)
        if not normalized:
            return None
        row = self._connection.execute(
            "SELECT security_id, name, industry, role, market FROM company WHERE security_id = ?",
            (normalized,),
        ).fetchone()
        return dict(row) if row else None

    def list_sources(self) -> list[dict[str, str]]:
        """列出数据来源和授权状态，供环境检查与人工审计使用。"""
        rows = self._connection.execute(
            "SELECT source_id, name, source_type, authorization_status, base_url, note "
            "FROM source ORDER BY source_id"
        ).fetchall()
        return [dict(row) for row in rows]

    def catalog_summary(self) -> dict[str, Any]:
        """返回目录规模与验证日期，不返回观测数据。"""
        counts = {
            table: int(self._connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("company", "source", "metric", "availability")
        }
        verified = self._connection.execute(
            "SELECT value FROM catalog_meta WHERE key = 'verified_on'"
        ).fetchone()
        return {
            "catalog_version": self.catalog_version,
            "verified_on": str(verified["value"]) if verified else None,
            "counts": counts,
        }

    def close(self) -> None:
        """关闭 SQLite 连接。"""
        self._connection.close()

    def _availability_for(self, *, metric_id: str, security_id: str | None) -> list[sqlite3.Row]:
        """优先返回公司专属配置，不存在时退回 ``*`` 通用配置。"""
        if security_id:
            exact = self._connection.execute(
                "SELECT * FROM availability WHERE metric_id = ? AND security_id = ?",
                (metric_id, security_id),
            ).fetchall()
            if exact:
                return exact
        return self._connection.execute(
            "SELECT * FROM availability WHERE metric_id = ? AND security_id = '*'",
            (metric_id,),
        ).fetchall()

    def _create_schema(self) -> None:
        """创建精简规范化表；仅存目录元数据，不复制生产业务表。"""
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS catalog_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS company (
                security_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                industry TEXT NOT NULL,
                role TEXT NOT NULL,
                market TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS source (
                source_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                source_type TEXT NOT NULL,
                authorization_status TEXT NOT NULL,
                base_url TEXT NOT NULL,
                note TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS metric (
                metric_id TEXT PRIMARY KEY,
                version TEXT NOT NULL,
                name TEXT NOT NULL,
                definition TEXT NOT NULL,
                unit TEXT NOT NULL,
                frequency TEXT NOT NULL,
                period_type TEXT NOT NULL,
                expected_direction TEXT,
                industries_json TEXT NOT NULL,
                keywords_json TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                threshold_policy TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS availability (
                metric_id TEXT NOT NULL,
                security_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                availability_grade TEXT NOT NULL,
                observation_frequency TEXT NOT NULL,
                polling_frequency TEXT NOT NULL,
                note TEXT NOT NULL,
                PRIMARY KEY (metric_id, security_id, source_id)
            );
            """
        )

    def _replace_seed(self, content: dict[str, Any]) -> None:
        """在单个事务中替换目录快照，避免混用不同版本。"""
        with self._connection:
            for table in ("catalog_meta", "availability", "metric", "source", "company"):
                self._connection.execute(f"DELETE FROM {table}")
            self._connection.executemany(
                "INSERT INTO catalog_meta(key, value) VALUES (?, ?)",
                [
                    ("catalog_version", str(content["catalog_version"])),
                    ("verified_on", str(content["verified_on"])),
                ],
            )
            self._connection.executemany(
                "INSERT INTO company VALUES (:security_id, :name, :industry, :role, :market)",
                content["companies"],
            )
            self._connection.executemany(
                "INSERT INTO source VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        item["source_id"],
                        item["name"],
                        item["source_type"],
                        item["authorization_status"],
                        item.get("base_url") or "",
                        item["note"],
                    )
                    for item in content["sources"]
                ],
            )
            self._connection.executemany(
                "INSERT INTO metric VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        item["metric_id"],
                        item["version"],
                        item["name"],
                        item["definition"],
                        item["unit"],
                        item["frequency"],
                        item["period_type"],
                        item.get("expected_direction"),
                        json.dumps(item["industries"], ensure_ascii=False),
                        json.dumps(item["keywords"], ensure_ascii=False),
                        item["relation_type"],
                        item["threshold_policy"],
                    )
                    for item in content["metrics"]
                ],
            )
            self._connection.executemany(
                "INSERT INTO availability VALUES "
                "(:metric_id, :security_id, :source_id, :availability_grade, "
                ":observation_frequency, :polling_frequency, :note)",
                content["availability"],
            )


def _normalize_security_id(security_id: str | None) -> str | None:
    """去掉常见交易所后缀，不改动港股前导零。"""
    if security_id is None:
        return None
    normalized = _EXCHANGE_SUFFIX.sub("", security_id.strip())
    return normalized or None


def _matching_reasons(
    hypothesis: str, *, metric_name: str, keywords: tuple[str, ...]
) -> tuple[list[str], int]:
    """只用明确业务短语计分，避免单字重合造成弱相关召回。"""
    normalized = hypothesis.strip().lower()
    hits = [keyword for keyword in keywords if keyword.lower() in normalized]
    reasons = [f"假设命中业务词“{keyword}”" for keyword in hits]
    score = len(hits) * 4
    if metric_name.lower() in normalized:
        reasons.insert(0, f"假设直接提及指标“{metric_name}”")
        score += 8
    return reasons, score


def _join_distinct(values: Any) -> str:
    """稳定拼接非空去重文本，方便向模型展示多个来源说明。"""
    return "；".join(dict.fromkeys(value for value in values if value))
