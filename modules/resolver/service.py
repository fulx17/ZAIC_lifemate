"""Public, model-free and tool-free argument resolver."""

from __future__ import annotations

from typing import Any

from core.contracts import PlanTask, ResolutionResult, ToolSpec
from modules.resolver.bindings import BindingError, bind_value
from modules.resolver.entity_matcher import validate_arguments


class ResolverService:
    def resolve(
        self, task: PlanTask, observations: dict[str, Any], tool_spec: ToolSpec
    ) -> ResolutionResult:
        try:
            arguments = bind_value(task.arguments, observations)
        except BindingError as exc:
            return ResolutionResult(
                status=exc.status,
                candidates=exc.candidates,
                message=str(exc),
            )
        except ValueError as exc:
            return ResolutionResult(status="INVALID", message=str(exc))

        properties = tool_spec.parameters.get("properties", {})
        if properties:
            arguments = {name: value for name, value in arguments.items() if name in properties}
        errors = validate_arguments(arguments, tool_spec.parameters)
        if errors:
            required_missing = [
                field
                for field in tool_spec.parameters.get("required", [])
                if arguments.get(field) in (None, "", [], {})
            ]
            if required_missing:
                field = required_missing[0]
                return ResolutionResult(status="NEEDS_USER", field=field, message="required value is missing")

            groups = tool_spec.parameters.get("x-one-of", [])
            if groups and not any(
                all(arguments.get(field) not in (None, "", [], {}) for field in group)
                for group in groups
            ):
                field = groups[0][0] if groups and groups[0] else None
                person_name = next(
                    (
                        task.arguments.get(name)
                        for name in ("recipient_name", "contact_name", "person_name")
                        if isinstance(task.arguments.get(name), str) and task.arguments[name].strip()
                    ),
                    None,
                )
                if person_name:
                    return ResolutionResult(
                        status="NEEDS_EXPLORE",
                        field=field,
                        suggested_tools=["contacts.search"],
                        suggested_arguments={"query": person_name},
                        message="unique contact lookup is required",
                    )
                return ResolutionResult(
                    status="NEEDS_USER",
                    field=field,
                    message="one required alternative is missing",
                )
            return ResolutionResult(status="INVALID", message="; ".join(errors))
        return ResolutionResult(status="READY", arguments=arguments)
