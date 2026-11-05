"""Public discovery service."""

from core.contracts import AgentRequest, ToolSpec
from modules.discovery.retriever import ToolRetriever


class DiscoveryService:
    def __init__(self, top_k: int = 8):
        self.retriever = ToolRetriever(top_k)

    def retrieve(self, request: AgentRequest, catalog: list[ToolSpec]) -> list[ToolSpec]:
        return self.retriever.retrieve(request, catalog)
