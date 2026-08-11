from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from analytics.experiments.run_signal_experiment import (
    CandidateEvent,
    SignalRecord,
    deduplicate_candidates,
    unconditional_baseline,
)
from analytics.pipelines.return_labels import QuoteBook, ReturnLabel


def _candidate(
    event_id: str,
    direction: str,
    *,
    trading_day: str,
    disclosure_time: str = "2025-01-01T18:00:00+08:00",
) -> CandidateEvent:
    return CandidateEvent(
        event_id=event_id,
        security_id="600000.SH",
        company="测试公司",
        title=event_id,
        disclosure_time=disclosure_time,
        split="in_sample",
        hypothesis="H1",
        direction=direction,
        label=ReturnLabel(
            security_id="600000.SH",
            disclosure_time=disclosure_time,
            window_start=trading_day,
            window_end="2025-02-01",
            security_return=Decimal("2"),
            benchmark_return=Decimal("1"),
            excess_return=Decimal("1"),
            status="已生成",
        ),
    )


def test_same_security_trading_day_is_merged_and_conflict_goes_to_review() -> None:
    candidates = [
        _candidate("EVT-1", "支持", trading_day="2025-01-02"),
        _candidate("EVT-2", "支持", trading_day="2025-01-02"),
        _candidate("EVT-3", "支持", trading_day="2025-01-03"),
        _candidate("EVT-4", "冲突", trading_day="2025-01-03"),
    ]

    records, stats = deduplicate_candidates(candidates)

    assert len(records) == 1
    assert records[0].source_event_count == 2
    assert records[0].source_event_ids == ("EVT-1", "EVT-2")
    assert stats.raw_directional_events == 4
    assert stats.duplicate_events_removed == 2
    assert stats.conflicting_groups_removed == 1
    assert stats.output_signals == 1


class FakeBook:
    def unconditional_excess_returns(
        self, security_id: str, *, start: str, end: str
    ) -> list[Decimal]:
        assert security_id == "600000.SH"
        assert start == end == "2025-01-01"
        return [Decimal("1"), Decimal("-1"), Decimal("2")]


def test_unconditional_baseline_respects_signal_direction() -> None:
    common = {
        "security_id": "600000.SH",
        "company": "测试公司",
        "title": "公告",
        "disclosure_time": "2025-01-01T18:00:00+08:00",
        "split": "out_of_sample",
        "hypothesis": "H1",
        "window_start": "2025-01-02",
        "window_end": "2025-02-01",
        "excess_return": Decimal("1"),
        "label_status": "已生成",
        "hit": True,
    }
    records = [
        SignalRecord(event_id="EVT-1", direction="支持", **common),
        SignalRecord(event_id="EVT-2", direction="冲突", **common),
    ]

    result = unconditional_baseline(records, FakeBook())  # type: ignore[arg-type]

    assert result.sample_count == 3
    assert result.expected_hit_rate == 0.5
    assert result.mean_excess == 0.6667


def test_quote_book_builds_unconditional_forward_windows(tmp_path: Path) -> None:
    days = [f"2025-01-{day:02d}" for day in range(1, 11)]
    payload = {
        "data_version": "test",
        "series": {
            "600000.SH": {day: str(100 + index) for index, day in enumerate(days)},
            "399006": {day: "100" for day in days},
        },
    }
    path = tmp_path / "quotes.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    values = QuoteBook(path).unconditional_excess_returns(
        "600000.SH", start="2025-01-01", end="2025-01-03", window_days=2
    )

    assert len(values) == 3
    assert all(value > 0 for value in values)
