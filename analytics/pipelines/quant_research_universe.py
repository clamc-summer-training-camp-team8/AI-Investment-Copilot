"""P2 量化研究池与前瞻样本协议的版本化读取和硬门禁。"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from typing import cast

from analytics.pipelines.universe import MARKET_A, Company

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = PROJECT_ROOT / "analytics" / "datasets" / "quant-p2-a-share-v1"
DEFAULT_UNIVERSE_PATH = DEFAULT_ROOT / "universe.json"
DEFAULT_PROTOCOL_PATH = DEFAULT_ROOT / "protocol.json"


@dataclass(frozen=True)
class QuantResearchUniverse:
    universe_id: str
    status: str
    as_of: datetime
    effective_from: date
    companies: tuple[Company, ...]
    benchmarks: dict[str, Company]
    sample_gate: dict[str, int]
    historical_controls: tuple[dict[str, object], ...]
    payload: dict[str, object]
    sha256: str


@dataclass(frozen=True)
class QuantSampleProtocol:
    protocol_id: str
    status: str
    universe_id: str
    prospective_start_at: datetime
    sample_gate: dict[str, int | bool]
    payload: dict[str, object]
    sha256: str

    def partition_for(self, observed_at: datetime) -> str:
        if observed_at.tzinfo is None:
            raise ValueError("样本时间必须包含时区")
        current = observed_at.date()
        partitions = cast(list[dict[str, object]], self.payload["time_partitions"])
        for item in partitions:
            start = date.fromisoformat(str(item["start"]))
            end_value = item.get("end")
            end = date.fromisoformat(str(end_value)) if end_value else None
            if current >= start and (end is None or current <= end):
                return str(item["name"])
        raise ValueError(f"样本时间 {current} 不在预注册分区内")


def _read(path: Path) -> tuple[dict[str, object], str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"治理资产必须是 JSON 对象: {path}")
    return cast(dict[str, object], payload), sha256(path.read_bytes()).hexdigest()


def _secid(security_id: str) -> str:
    if len(security_id) != 6 or not security_id.isdigit():
        raise ValueError(f"P2 研究池只支持六位 A 股代码: {security_id}")
    return f"{'1' if security_id.startswith('6') else '0'}.{security_id}"


def load_quant_research_universe(
    path: Path = DEFAULT_UNIVERSE_PATH,
) -> QuantResearchUniverse:
    payload, digest = _read(path)
    if payload.get("schema_version") != "quant-research-universe-v1":
        raise ValueError("P2 研究池版本不受支持")
    if payload.get("market") != MARKET_A or payload.get("currency") != "CNY":
        raise ValueError("P2 研究池必须保持纯 A 股、人民币同口径")

    as_of = datetime.fromisoformat(str(payload["as_of"]))
    if as_of.tzinfo is None:
        raise ValueError("P2 研究池 as_of 必须包含时区")
    effective_from = date.fromisoformat(str(payload["effective_from"]))
    members = cast(list[dict[str, object]], payload.get("members"))
    if not 20 <= len(members) <= 30:
        raise ValueError("P2 研究池必须包含 20–30 只证券")

    companies: list[Company] = []
    seen: set[str] = set()
    for item in members:
        security_id = str(item["security_id"])
        if security_id in seen:
            raise ValueError(f"P2 研究池证券重复: {security_id}")
        seen.add(security_id)
        if item.get("membership_end") is not None:
            raise ValueError(f"当前候选池不能包含已结束成员: {security_id}")
        membership_start = date.fromisoformat(str(item["membership_start"]))
        if membership_start < effective_from:
            raise ValueError(f"研究池成员资格禁止倒签: {security_id}")
        if item.get("listing_status") != "active" or item.get("signal_eligible") is not True:
            raise ValueError(f"当前研究池成员必须在市且允许前瞻信号: {security_id}")
        companies.append(
            Company(
                security_id=security_id,
                name=str(item["name"]),
                org_id="",
                secid=_secid(security_id),
                industry=str(item["industry"]),
                role=str(item["role"]),
                market=MARKET_A,
            )
        )

    selection = cast(dict[str, object], payload["selection_policy"])
    expected_quota = int(str(selection["industry_quota"]))
    industry_counts = Counter(company.industry for company in companies)
    if set(industry_counts) != set(cast(list[str], selection["industries"])):
        raise ValueError("研究池行业集合与选择策略不一致")
    if any(count != expected_quota for count in industry_counts.values()):
        raise ValueError("研究池没有满足预注册行业配额")

    raw_benchmarks = cast(dict[str, dict[str, object]], payload["benchmarks"])
    if set(raw_benchmarks) != set(industry_counts):
        raise ValueError("每个研究行业必须事前绑定一个基准")
    benchmarks = {
        industry: Company(
            security_id=str(item["security_id"]),
            name=str(item["name"]),
            org_id="",
            secid=str(item["secid"]),
            industry=industry,
            role="基准",
            market=MARKET_A,
        )
        for industry, item in raw_benchmarks.items()
    }
    sample_gate = {
        key: int(str(value))
        for key, value in cast(dict[str, object], payload["sample_gate"]).items()
    }
    controls = cast(dict[str, object], payload["historical_controls"])
    control_members = tuple(cast(list[dict[str, object]], controls.get("members") or []))
    if any(item.get("signal_eligible") is not False for item in control_members):
        raise ValueError("退市对照样本不得进入前瞻信号池")

    return QuantResearchUniverse(
        universe_id=str(payload["universe_id"]),
        status=str(payload["status"]),
        as_of=as_of,
        effective_from=effective_from,
        companies=tuple(companies),
        benchmarks=benchmarks,
        sample_gate=sample_gate,
        historical_controls=control_members,
        payload=payload,
        sha256=digest,
    )


def load_quant_sample_protocol(path: Path = DEFAULT_PROTOCOL_PATH) -> QuantSampleProtocol:
    payload, digest = _read(path)
    if payload.get("schema_version") != "quant-prospective-sample-protocol-v1":
        raise ValueError("P2 前瞻样本协议版本不受支持")
    prospective_start = datetime.fromisoformat(str(payload["prospective_start_at"]))
    if prospective_start.tzinfo is None:
        raise ValueError("P2 前瞻起点必须包含时区")
    gate = cast(dict[str, int | bool], payload["research_candidate_gate"])
    if gate.get("alpha_claim_allowed") is not False:
        raise ValueError("P2 自动门槛不得授予 Alpha 宣称权限")
    if gate.get("requires_independent_review") is not True:
        raise ValueError("P2 研究候选必须要求独立评审")
    return QuantSampleProtocol(
        protocol_id=str(payload["protocol_id"]),
        status=str(payload["status"]),
        universe_id=str(payload["universe_id"]),
        prospective_start_at=prospective_start,
        sample_gate=gate,
        payload=payload,
        sha256=digest,
    )


def load_quant_research_governance(
    universe_path: Path = DEFAULT_UNIVERSE_PATH,
    protocol_path: Path = DEFAULT_PROTOCOL_PATH,
) -> tuple[QuantResearchUniverse, QuantSampleProtocol]:
    universe = load_quant_research_universe(universe_path)
    protocol = load_quant_sample_protocol(protocol_path)
    if protocol.universe_id != universe.universe_id:
        raise ValueError("P2 样本协议绑定的研究池版本不一致")
    return universe, protocol
