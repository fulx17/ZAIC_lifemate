"""Read-only registry over the environment's per-sample tool catalog."""

from __future__ import annotations

from core.contracts import ToolSpec
from modules.discovery.capabilities import infer_tool_app, infer_tool_kind


class ToolRegistry:
    def __init__(self, tools: list[ToolSpec]):
        self._tools = {tool.name: tool for tool in tools}
        if len(self._tools) != len(tools):
            raise ValueError("tool catalog contains duplicate names")

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def all(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def by_app(self, app: str) -> list[ToolSpec]:
        return [tool for tool in self._tools.values() if infer_tool_app(tool) == app]

    def read_only_tools(self) -> list[ToolSpec]:
        return [
            tool
            for tool in self._tools.values()
            if infer_tool_kind(tool) == "read" and tool.name != "sys.ask_missing_info"
        ]
