"""Mock and thin adapters over the supplied zaic_tools APIs."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from core.contracts import ToolSpec


class MockEnvironment:
    def __init__(
        self,
        schemas: list[ToolSpec],
        responses: dict[str, Any] | None = None,
        *,
        initial_state: dict[str, Any] | None = None,
    ):
        self.schemas = {schema.name: schema for schema in schemas}
        self.responses = responses or {}
        self.state = copy.deepcopy(initial_state or {})
        self.calls: list[dict[str, Any]] = []

    def list_available_tools(self) -> list[ToolSpec]:
        return [schema.model_copy(deep=True) for schema in self.schemas.values()]

    def validate(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        schema = self.schemas.get(name)
        if schema is None:
            return {"ok": False, "error": f"tool {name!r} not installed"}
        parameters = schema.parameters
        properties = parameters.get("properties", {})
        required = parameters.get("required", [])
        missing = [key for key in required if arguments.get(key) in (None, "", [], {})]
        if missing:
            return {"ok": False, "error": f"missing required arguments: {missing}"}
        for key, value in arguments.items():
            spec = properties.get(key)
            if spec and spec.get("enum") and value not in spec["enum"]:
                return {"ok": False, "error": f"invalid enum for {key}"}
        return {"ok": True, "error": None}

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        validation = self.validate(name, arguments)
        if not validation["ok"]:
            return {"ok": False, "error": validation["error"]}
        self.calls.append({"name": name, "arguments": copy.deepcopy(arguments)})
        response = self.responses.get(name)
        if callable(response):
            result = response(arguments, self.state)
        elif response is not None:
            result = copy.deepcopy(response)
        else:
            result = self._default_response(name, arguments)
        return copy.deepcopy(result)

    def get_tool_calls(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self.calls)

    def get_state_hash(self) -> str:
        payload = json.dumps(self.state, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
        return hashlib.sha256(payload).hexdigest()

    def _default_response(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "weather.get_forecast":
            date = arguments.get("date", "tomorrow")
            return {"ok": True, "forecast": [{"date": date, "rain": False}]}
        if name == "calendar.list_events":
            return {"ok": True, "events": copy.deepcopy(self.state.get("events", []))}
        if name == "calendar.update_event":
            events = self.state.get("events", [])
            for event in events:
                if event.get("id") == arguments.get("event_id"):
                    event.update({key: arguments[key] for key in ("start", "end") if key in arguments})
            self.state["events"] = events
            return {"ok": True, "item": {**arguments}}
        if name == "contacts.search":
            query = arguments.get("query", "")
            return {"ok": True, "contacts": [{"id": "mock_contact", "name": query}]}
        if name == "sms.send":
            messages = self.state.setdefault("messages", [])
            message = {"id": f"mock_message_{len(messages) + 1}", **arguments}
            messages.append(message)
            return {"ok": True, "message": message}
        return {"ok": True, "result": {}}


class OfficialEnvironment:
    """Per-sample wrapper around the kit's documented ToolEnv API."""

    def __init__(self, bundle_root: str | Path, split: str, sample_id: str):
        self.bundle_root = Path(bundle_root).resolve()
        package_dir = self.bundle_root / split / "zaic_tools"
        init_path = package_dir / "__init__.py"
        if not init_path.is_file():
            raise FileNotFoundError(f"Official zaic_tools package is missing: {package_dir}")
        alias = f"_lifemate_zaic_tools_{split}"
        package = sys.modules.get(alias)
        if package is None:
            spec = importlib.util.spec_from_file_location(
                alias, init_path, submodule_search_locations=[str(package_dir)]
            )
            if spec is None or spec.loader is None:
                raise ImportError(f"Cannot load local kit package from {package_dir}")
            package = importlib.util.module_from_spec(spec)
            sys.modules[alias] = package
            spec.loader.exec_module(package)
        self._session = package.ToolEnv(split, sample_id, root=str(self.bundle_root))
        self._catalog_tools = self._session.tools
        self._allowed = set(self._session.allowed)

    def list_available_tools(self) -> list[ToolSpec]:
        schemas = []
        for name in sorted(self._allowed):
            spec = self._catalog_tools.get(name)
            if spec is None:
                continue
            schemas.append(
                ToolSpec(
                    name=name,
                    description=spec.get("description", ""),
                    parameters=spec.get("parameters", {}),
                    kind=spec.get("kind"),
                    app=spec.get("app"),
                )
            )
        return schemas

    def validate(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._session.validate(name, arguments)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._session.call(name, arguments)

    def get_tool_calls(self) -> list[dict[str, Any]]:
        return self._session.get_tool_calls()

    def get_state_hash(self) -> str:
        return self._session.get_state_hash()

    def get_state(self) -> dict[str, Any]:
        return self._session.get_state()


def load_catalog_schemas(bundle_root: str | Path, split: str, installed_apps: dict[str, Any]) -> list[ToolSpec]:
    catalog_path = Path(bundle_root) / split / f"{split}_tools_catalog.json"
    if not catalog_path.is_file():
        raise FileNotFoundError(f"Tool catalog missing: {catalog_path}")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    allowed = {tool for app in installed_apps.values() for tool in app.get("tools", [])} | {"sys.ask_missing_info"}
    schemas = []
    for app in catalog.get("apps", []):
        for tool in app.get("tools", []):
            if tool["name"] in allowed:
                schemas.append(
                    ToolSpec(
                        name=tool["name"],
                        description=tool.get("description", ""),
                        parameters=tool.get("parameters", {}),
                        kind=tool.get("kind"),
                        app=tool.get("app", app.get("id")),
                    )
                )
    return schemas
