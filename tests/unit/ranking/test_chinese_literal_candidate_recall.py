from app.ranking.scorer import _cjk_literal_relevance


def test_literal_relevance_prefers_matching_chinese_fact() -> None:
    query = "投资活动现金流扩大流出"
    matching = "2025年投资活动产生的现金流量净额为流出13.91亿元。"
    title_noise = "关于召开年度股东大会的公告"

    assert _cjk_literal_relevance(query, matching) > _cjk_literal_relevance(query, title_noise)
