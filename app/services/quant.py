"""量化研究服务：把研究信号映射为确定性回测输入。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any

from app.calc.backtest import (
    BacktestConfig,
    BacktestResult,
    MarketBar,
    StrategySignal,
    run_event_backtest,
)
from app.calc.portfolio import (
    PortfolioBar,
    PortfolioConfig,
    PortfolioInputError,
    PortfolioSignal,
    run_portfolio_backtest,
)
from app.core.config import PROJECT_ROOT, settings
from app.core.domain import (
    AuditRecord,
    QuantBacktestRecord,
    QuantMarketDatasetRecord,
    QuantSignalSetRecord,
    UnitOfWork,
)
from app.core.timeutil import now
from app.services.market_data import FrozenJsonMarketData, MarketDataError

_DIRECTION_SIGN = {"支持": Decimal(1), "冲突": Decimal(-1), "中性": Decimal(0)}
_STRENGTH_WEIGHT = {"高": Decimal(1), "中": Decimal("0.7"), "低": Decimal("0.4")}


@dataclass(frozen=True)
class QuantBarInput:
    trading_date: date
    close: Decimal
    benchmark_close: Decimal
    tradable: bool = True


@dataclass(frozen=True)
class QuantSignalInput:
    signal_id: str
    disclosed_at: datetime
    generated_at: datetime
    direction: str
    strength: str
    confidence: Decimal


@dataclass(frozen=True)
class QuantBacktestRun:
    run_id: str
    name: str
    generated_at: datetime
    result: BacktestResult


@dataclass(frozen=True)
class FrozenSignalInput:
    signal_id: str
    security_id: str
    disclosed_at: datetime
    generated_at: datetime
    direction: str
    strength: str
    confidence: Decimal
    confirmation_status: str
    source_evidence_id: str
    source_relation_id: str


def _signal_score(signal: QuantSignalInput) -> Decimal:
    try:
        sign = _DIRECTION_SIGN[signal.direction]
        strength = _STRENGTH_WEIGHT[signal.strength]
    except KeyError as exc:
        raise ValueError(f"未知信号方向或强度: {exc.args[0]}") from exc
    return sign * strength * signal.confidence


def _run_id(
    *,
    name: str,
    bars: list[QuantBarInput],
    signals: list[QuantSignalInput],
    config: BacktestConfig,
) -> str:
    payload = {
        "name": name,
        "bars": [asdict(item) for item in bars],
        "signals": [asdict(item) for item in signals],
        "config": asdict(config),
        "methodology": "event-backtest-v1",
    }
    digest = sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return f"QBT-{digest[:16]}"


def run_quant_backtest(
    *,
    name: str,
    bars: list[QuantBarInput],
    signals: list[QuantSignalInput],
    config: BacktestConfig,
) -> QuantBacktestRun:
    """运行量化回测；相同输入与方法版本产生相同 run_id。"""
    market_bars = [
        MarketBar(
            trading_date=item.trading_date,
            close=item.close,
            benchmark_close=item.benchmark_close,
            tradable=item.tradable,
        )
        for item in bars
    ]
    strategy_signals = [
        StrategySignal(
            signal_id=item.signal_id,
            disclosed_at=item.disclosed_at,
            generated_at=item.generated_at,
            score=_signal_score(item),
        )
        for item in signals
    ]
    result = run_event_backtest(market_bars, strategy_signals, config)
    return QuantBacktestRun(
        run_id=_run_id(name=name, bars=bars, signals=signals, config=config),
        name=name,
        generated_at=now(),
        result=result,
    )


def _jsonable(value: object) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _resolve_market_manifest(manifest_path: Path) -> Path:
    candidate = manifest_path if manifest_path.is_absolute() else PROJECT_ROOT / manifest_path
    resolved = candidate.resolve()
    market_root = (PROJECT_ROOT / "real_data" / "quant").resolve()
    if market_root not in resolved.parents:
        raise MarketDataError("冻结行情清单必须位于 real_data/quant 受治理目录")
    if not resolved.is_file():
        raise MarketDataError(f"冻结行情清单不存在: {resolved}")
    return resolved


def validate_market_dataset(
    manifest_path: Path,
    *,
    expected_sha256: str | None = None,
    expected_dataset_id: str | None = None,
    frozen_by: str,
) -> QuantMarketDatasetRecord:
    """校验任意受治理候选清单并构造待登记记录，不写数据库。"""

    resolved = _resolve_market_manifest(manifest_path)
    manifest_sha256 = sha256(resolved.read_bytes()).hexdigest()
    if expected_sha256 is not None and manifest_sha256 != expected_sha256.lower():
        raise MarketDataError(
            "冻结行情清单哈希与发布审批值不一致: "
            f"expected={expected_sha256.lower()}, actual={manifest_sha256}"
        )
    adapter = FrozenJsonMarketData(resolved)
    info = adapter.info()
    if expected_dataset_id is not None and info.dataset_id != expected_dataset_id:
        raise MarketDataError(
            "冻结行情数据集编号与发布审批值不一致: "
            f"expected={expected_dataset_id}, actual={info.dataset_id}"
        )
    return QuantMarketDatasetRecord(
        dataset_id=info.dataset_id,
        data_version=info.data_version,
        manifest_path=resolved.relative_to(PROJECT_ROOT.resolve()).as_posix(),
        manifest_sha256=manifest_sha256,
        source_policy_id=info.source_policy_id,
        authorization_status=info.authorization_status,
        adjustment=info.adjustment,
        coverage_start=info.coverage_start,
        coverage_end=info.coverage_end,
        securities=list(info.securities),
        capabilities=info.capabilities,
        limitations=list(info.limitations),
        status="frozen",
        frozen_by=frozen_by,
        frozen_at=now(),
    )


def register_market_dataset(
    uow: UnitOfWork,
    *,
    manifest_path: Path,
    frozen_by: str,
    expected_sha256: str | None = None,
    expected_dataset_id: str | None = None,
) -> QuantMarketDatasetRecord:
    """登记指定冻结行情；登记动作本身不改变在线默认版本。"""

    record = validate_market_dataset(
        manifest_path,
        expected_sha256=expected_sha256,
        expected_dataset_id=expected_dataset_id,
        frozen_by=frozen_by,
    )
    existing = uow.quant.get_market_dataset(record.dataset_id)
    if existing is not None:
        if existing.manifest_sha256 != record.manifest_sha256:
            raise MarketDataError("数据集编号已登记，但清单哈希不同；必须提升数据集版本")
        if existing.data_version != record.data_version:
            raise MarketDataError("数据集编号已登记，但数据版本不同；必须提升数据集版本")
        return existing
    same_version = next(
        (
            item
            for item in uow.quant.list_market_datasets()
            if item.data_version == record.data_version
        ),
        None,
    )
    if same_version is not None:
        raise MarketDataError("数据版本已登记到其他数据集编号；禁止复用版本号")
    uow.quant.add_market_dataset(record)
    uow.audit.add(
        AuditRecord(
            actor=frozen_by,
            action="quant.market_dataset.freeze",
            object_type="quant_market_dataset",
            object_id=record.dataset_id,
            detail={"manifest_sha256": record.manifest_sha256},
        )
    )
    return record


def register_default_market_dataset(uow: UnitOfWork, *, frozen_by: str) -> QuantMarketDatasetRecord:
    """兼容入口：登记当前配置清单，但不隐式改变默认版本配置。"""

    return register_market_dataset(
        uow,
        manifest_path=settings.quant_default_market_manifest,
        frozen_by=frozen_by,
    )


def configured_default_market_dataset_id(uow: UnitOfWork) -> str | None:
    """返回已登记且哈希匹配的显式默认数据集；未登记时不猜测最新版本。"""

    manifest_path = _resolve_market_manifest(settings.quant_default_market_manifest)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        dataset_id = str(payload["dataset_id"])
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        raise MarketDataError("无法识别默认冻结行情清单的数据集编号") from exc
    existing = uow.quant.get_market_dataset(dataset_id)
    if existing is None:
        return None
    actual_sha256 = sha256(manifest_path.read_bytes()).hexdigest()
    if existing.manifest_sha256 != actual_sha256:
        raise MarketDataError("默认行情清单哈希与数据库登记值不一致")
    return existing.dataset_id


def market_dataset_detail(
    uow: UnitOfWork, *, dataset_id: str, requested_by: str
) -> dict[str, object]:
    """Return a governed, read-only view of one registered market dataset."""
    record = uow.quant.get_market_dataset(dataset_id)
    if record is None:
        raise LookupError("冻结行情数据集不存在")
    manifest_path = _resolve_market_manifest(Path(record.manifest_path))
    actual_manifest_sha256 = sha256(manifest_path.read_bytes()).hexdigest()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MarketDataError("冻结行情清单无法读取") from exc
    raw_assets = manifest.get("assets")
    if not isinstance(raw_assets, dict):
        raise MarketDataError("冻结行情清单缺少 assets")
    assets: list[dict[str, object]] = []
    for name, raw in sorted(raw_assets.items()):
        if not isinstance(raw, dict):
            raise MarketDataError(f"冻结行情子资产格式无效: {name}")
        relative = Path(str(raw.get("path", "")))
        candidate = (manifest_path.parent / relative).resolve()
        if manifest_path.parent.resolve() not in candidate.parents:
            raise MarketDataError(f"冻结行情子资产越出数据集目录: {name}")
        expected = str(raw.get("sha256", ""))
        exists = candidate.is_file()
        actual = sha256(candidate.read_bytes()).hexdigest() if exists else None
        assets.append(
            {
                "name": str(name),
                "path": relative.as_posix(),
                "sha256": expected,
                "byte_size": candidate.stat().st_size if exists else None,
                "verified": exists and actual == expected,
            }
        )
    try:
        default_dataset_id = configured_default_market_dataset_id(uow)
    except MarketDataError:
        default_dataset_id = None
    authorization = manifest.get("authorization")
    authorization_scope = (
        str(authorization.get("scope"))
        if isinstance(authorization, dict) and authorization.get("scope")
        else None
    )
    runs = [
        item
        for item in uow.quant.list_backtests(requested_by, limit=1000)
        if item.market_dataset_id == dataset_id
    ]
    return {
        "record": record,
        "is_default": default_dataset_id == dataset_id,
        "manifest_verified": actual_manifest_sha256 == record.manifest_sha256
        and all(bool(item["verified"]) for item in assets),
        "assets": assets,
        "source_priority": [str(item) for item in manifest.get("source_priority", [])],
        "authorization_scope": authorization_scope,
        "timezone": str(manifest.get("timezone", "Asia/Shanghai")),
        "adjustment_anchor_date": manifest.get("adjustment_anchor_date"),
        "available_signal_sets": uow.quant.list_signal_sets(),
        "backtest_count": len(runs),
    }


def freeze_signal_set(
    uow: UnitOfWork,
    *,
    name: str,
    version: str,
    signals: list[FrozenSignalInput],
    frozen_by: str,
) -> QuantSignalSetRecord:
    """冻结人工确认信号；语义/检索结果不能通过此入口冒充 Alpha 信号。"""
    if not signals:
        raise ValueError("信号集不能为空")
    if len({item.signal_id for item in signals}) != len(signals):
        raise ValueError("信号编号必须唯一")
    for signal in signals:
        if signal.confirmation_status != "已确认":
            raise ValueError(f"{signal.signal_id}: 只有人工已确认信号可以冻结")
        if signal.generated_at < signal.disclosed_at:
            raise ValueError(f"{signal.signal_id}: 生成时间早于披露时间")
        if not signal.source_evidence_id:
            raise ValueError(f"{signal.signal_id}: 缺少已确认证据编号")
        evidence = uow.evidence.get(signal.source_evidence_id)
        if evidence is None:
            raise ValueError(f"{signal.signal_id}: 已确认证据不存在")
        relation = uow.relations.get(signal.source_relation_id)
        if relation is None or relation.evidence_id != evidence.evidence_id:
            raise ValueError(f"{signal.signal_id}: 已确认关系不存在或与证据不一致")
        if relation.status.value != "已确认" or relation.reviewed_at is None:
            raise ValueError(f"{signal.signal_id}: 来源关系尚未完成真实人工确认")
        if signal.generated_at < relation.reviewed_at:
            raise ValueError(f"{signal.signal_id}: 信号生成时间早于人工确认时间")
        if evidence.security_id != signal.security_id:
            raise ValueError(f"{signal.signal_id}: 信号证券与来源证据不一致")
        if evidence.disclosed_at != signal.disclosed_at:
            raise ValueError(f"{signal.signal_id}: 披露时间与来源证据不一致")
        if relation.direction.value != signal.direction:
            raise ValueError(f"{signal.signal_id}: 信号方向与人工确认关系不一致")
        _signal_score(
            QuantSignalInput(
                signal_id=signal.signal_id,
                disclosed_at=signal.disclosed_at,
                generated_at=signal.generated_at,
                direction=signal.direction,
                strength=signal.strength,
                confidence=signal.confidence,
            )
        )
    payload = [_jsonable(asdict(item)) for item in sorted(signals, key=lambda item: item.signal_id)]
    content_sha256 = sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    signal_set_id = f"QSS-{content_sha256[:20]}"
    existing = uow.quant.get_signal_set(signal_set_id)
    if existing is not None:
        return existing
    same_version = next(
        (item for item in uow.quant.list_signal_sets() if item.version == version), None
    )
    if same_version is not None:
        raise ValueError("信号版本已冻结；内容变化必须提升版本，禁止覆盖旧版本")
    record = QuantSignalSetRecord(
        signal_set_id=signal_set_id,
        name=name,
        version=version,
        content_sha256=content_sha256,
        signals=payload,
        signal_count=len(payload),
        human_confirmed_only=True,
        evaluation_track="alpha_validation",
        status="frozen",
        frozen_by=frozen_by,
        frozen_at=now(),
    )
    uow.quant.add_signal_set(record)
    uow.audit.add(
        AuditRecord(
            actor=frozen_by,
            action="quant.signal_set.freeze",
            object_type="quant_signal_set",
            object_id=record.signal_set_id,
            detail={
                "content_sha256": record.content_sha256,
                "signal_count": record.signal_count,
                "evaluation_track": record.evaluation_track,
            },
        )
    )
    return record


def _manifest_path(record: QuantMarketDatasetRecord) -> Path:
    path = (PROJECT_ROOT / record.manifest_path).resolve()
    if PROJECT_ROOT.resolve() not in path.parents:
        raise MarketDataError("冻结行情清单路径越出项目目录")
    if not path.is_file():
        raise MarketDataError("冻结行情清单不存在")
    actual = sha256(path.read_bytes()).hexdigest()
    if actual != record.manifest_sha256:
        raise MarketDataError("数据库登记的行情清单哈希与文件不一致")
    return path


def ensure_market_cap_neutralization_scope(
    capabilities: dict[str, bool], bars: list[PortfolioBar]
) -> None:
    """能力先按冻结声明准入，再按本次所选证券逐行验证点时覆盖。"""

    declared = capabilities.get("point_in_time_market_cap", False) or capabilities.get(
        "a_share_point_in_time_market_cap", False
    )
    if not declared:
        raise PortfolioInputError("当前冻结行情不含已核验点时市值，禁止声称已完成市值中性回测")
    if any(item.market_cap is None for item in bars):
        raise PortfolioInputError("所选证券区间存在点时市值缺口，禁止执行市值中性回测")


def run_versioned_portfolio_backtest(
    uow: UnitOfWork,
    *,
    name: str,
    market_dataset_id: str,
    signal_set_id: str,
    security_ids: tuple[str, ...],
    start: date | None,
    end: date | None,
    config: PortfolioConfig,
    requested_by: str,
) -> QuantBacktestRecord:
    dataset = uow.quant.get_market_dataset(market_dataset_id)
    signal_set = uow.quant.get_signal_set(signal_set_id)
    if dataset is None:
        raise LookupError("冻结行情集不存在")
    if signal_set is None:
        raise LookupError("冻结信号集不存在")
    if dataset.status != "frozen" or signal_set.status != "frozen":
        raise ValueError("行情集和信号集必须冻结后才能回测")
    if signal_set.evaluation_track != "alpha_validation":
        raise ValueError("语义或检索评测资产不得进入 Alpha 回测")
    if not signal_set.human_confirmed_only:
        raise ValueError("信号集含未经人工确认的候选")
    if config.enforce_capacity and not dataset.capabilities.get("capacity_constraint", False):
        raise PortfolioInputError("当前冻结行情不含容量约束所需成交额")
    if not security_ids:
        raise ValueError("至少选择一只证券")

    adapter = FrozenJsonMarketData(_manifest_path(dataset))
    bars = adapter.bars(security_ids, start=start, end=end)
    if config.neutralize_market_cap:
        ensure_market_cap_neutralization_scope(dataset.capabilities, bars)
    frozen_signals = [
        PortfolioSignal(
            signal_id=str(item["signal_id"]),
            security_id=str(item["security_id"]),
            disclosed_at=datetime.fromisoformat(str(item["disclosed_at"])),
            generated_at=datetime.fromisoformat(str(item["generated_at"])),
            score=_signal_score(
                QuantSignalInput(
                    signal_id=str(item["signal_id"]),
                    disclosed_at=datetime.fromisoformat(str(item["disclosed_at"])),
                    generated_at=datetime.fromisoformat(str(item["generated_at"])),
                    direction=str(item["direction"]),
                    strength=str(item["strength"]),
                    confidence=Decimal(str(item["confidence"])),
                )
            ),
        )
        for item in signal_set.signals
        if str(item["security_id"]) in security_ids
    ]
    if not frozen_signals:
        raise ValueError("所选证券没有冻结信号")
    result = run_portfolio_backtest(bars, frozen_signals, config)
    parameters = _jsonable(
        {
            "security_ids": security_ids,
            "start": start,
            "end": end,
            "config": asdict(config),
        }
    )
    run_payload = {
        "market_dataset_id": market_dataset_id,
        "market_manifest_sha256": dataset.manifest_sha256,
        "signal_set_id": signal_set_id,
        "signal_content_sha256": signal_set.content_sha256,
        "parameters": parameters,
        "methodology": result.methodology_version,
        "requested_by": requested_by,
    }
    digest = sha256(
        json.dumps(run_payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    run_id = f"QPF-{digest[:20]}"
    existing = uow.quant.get_backtest(run_id)
    if existing is not None:
        return existing
    record = QuantBacktestRecord(
        run_id=run_id,
        name=name,
        market_dataset_id=market_dataset_id,
        signal_set_id=signal_set_id,
        methodology_version=result.methodology_version,
        parameters=parameters,
        result=_jsonable(asdict(result)),
        evaluation_track="alpha_validation",
        requested_by=requested_by,
        generated_at=now(),
    )
    uow.quant.add_backtest(record)
    uow.audit.add(
        AuditRecord(
            actor=requested_by,
            action="quant.backtest.create",
            object_type="quant_backtest_run",
            object_id=record.run_id,
            detail={
                "market_dataset_id": market_dataset_id,
                "signal_set_id": signal_set_id,
                "methodology_version": record.methodology_version,
            },
        )
    )
    return record
