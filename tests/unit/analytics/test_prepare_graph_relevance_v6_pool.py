from __future__ import annotations

from analytics.pipelines.prepare_graph_relevance_v5_pool import QUERY_SPECS as V5_QUERY_SPECS
from analytics.pipelines.prepare_graph_relevance_v6_pool import QUERY_SPECS


def test_v6_has_thirty_new_query_ids_and_shared_company_scope() -> None:
    assert len(QUERY_SPECS) == 30
    assert len({spec.query_id for spec in QUERY_SPECS}) == 30
    assert all(spec.query_id.startswith("V6-Q") for spec in QUERY_SPECS)
    assert {spec.query_id for spec in QUERY_SPECS}.isdisjoint(
        {spec.query_id for spec in V5_QUERY_SPECS}
    )
    assert len({spec.hypothesis for spec in QUERY_SPECS}) == 30
    assert len({spec.security_id for spec in QUERY_SPECS}) == 9


def test_v6_queries_cover_quality_growth_cash_flow_and_risk_dimensions() -> None:
    hypotheses = " ".join(spec.hypothesis for spec in QUERY_SPECS)
    for term in ("毛利率", "收入", "现金", "研发", "库存", "风险", "海外", "资本开支"):
        assert term in hypotheses
