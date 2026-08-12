from __future__ import annotations

from app.ingest.facts import extract_key_facts
from app.ingest.segmentation import Segment


def _segment(text: str) -> Segment:
    return Segment("DOC-1", "DOC-1#paragraph-1", 1, text)


def test_抽取营业收入同比区间() -> None:
    facts = extract_key_facts([_segment("预计营业收入为59.5亿元，比上年同期增长23.35%至50.91%。")])

    assert len(facts) == 1
    assert facts[0].fact_type == "revenue_yoy"
    assert facts[0].direction == "增长"
    assert str(facts[0].change_rate_low) == "0.2335"
    assert str(facts[0].change_rate_high) == "0.5091"


def test_抽取交付量同比下降() -> None:
    facts = extract_key_facts([_segment("公司本月交付量20,011辆，较上年同月下降约34%。")])

    assert len(facts) == 1
    assert facts[0].fact_type == "delivery_yoy"
    assert facts[0].direction == "下降"
    assert str(facts[0].change_rate_low) == "0.34"


def test_支持带符号的同比表达() -> None:
    facts = extract_key_facts([_segment("本期营业收入57.66亿元，同比-29.08%。")])

    assert facts[0].direction == "下降"
    assert str(facts[0].change_rate_low) == "0.2908"


def test_没有同比方向时不猜测() -> None:
    assert extract_key_facts([_segment("公司本月交付20,011辆。")]) == []
