"""Public discovery service."""

from core.contracts import AgentRequest, InformationNeed, ToolCandidate, ToolSpec
from modules.discovery.retriever import ToolRetriever


class DiscoveryService:
    def __init__(self, top_k: int = 8, recovery_top_k: int | None = None):
        self.retriever = ToolRetriever(top_k, recovery_top_k)

    def retrieve(self, request: AgentRequest, catalog: list[ToolSpec]) -> list[ToolSpec]:
        return self.retriever.retrieve(request, catalog)

    def retrieve_for_need(
        self,
        need: InformationNeed,
        catalog: list[ToolSpec],
        history: list[str] | None = None,
    ) -> list[ToolCandidate]:
        return self.retriever.retrieve_for_need(need, catalog, history)
