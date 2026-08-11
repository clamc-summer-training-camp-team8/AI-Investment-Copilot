from app.ai.agent import EvidenceAgent as CompatibleEvidenceAgent
from app.ai.agent import InvestmentLogicChangeAgent as CompatibleLogicChangeAgent
from app.ai.agents import EvidenceAgent, InvestmentLogicChangeAgent


def test_legacy_agent_module_reexports_split_implementations() -> None:
    assert CompatibleEvidenceAgent is EvidenceAgent
    assert CompatibleLogicChangeAgent is InvestmentLogicChangeAgent
