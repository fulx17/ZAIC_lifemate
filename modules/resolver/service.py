"""Model-free argument binding, provenance checks, and information-need detection."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any

from core.contracts import (
    InformationNeed,
    PlanTask,
    ResolutionIssue,
    ResolutionResult,
    ToolSpec,
)
from modules.resolver.bindings import BindingError, bind_value
from modules.resolver.entity_matcher import validate_arguments

_LOCATION_FIELDS = {"address", "location", "pickup", "dropoff", "destination", "origin"}
_TIME_FIELDS = {"date", "time", "datetime", "schedule", "schedule_time", "start", "end"}
_ENTITY_FIELDS = {"recipient", "recipient_id", "contact", "contact_id", "identity", "person", "account"}
_GENERIC_DESTINATIONS = {
    "khám răng",
    "đi khám răng",
    "nha khoa",
    "phòng khám nha khoa",
    "dental appointment",
    "dental exam",
    "clinic",
    "dentist",
}
_GENERIC_LOCATION_ALIASES = {
    "công ty": ("user_profile.work_address", "work_address"),
    "văn phòng": ("user_profile.work_address", "work_address"),
    "work": ("user_profile.work_address", "work_address"),
    "office": ("user_profile.work_address", "work_address"),
    "nhà": ("user_profile.home_address", "home_address"),
    "home": ("user_profile.home_address", "home_address"),
}
_DEFAULT_PROVENANCE_CATEGORIES = {
    "time",
    "location",
    "recipient",
    "identity",
    "amount",
    "payment",
}


class _ExpressionIssue(ValueError):
    def __init__(self, code: str, message: str, *, kind: str = "ARGUMENT", constraints: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.kind = kind
        self.constraints = constraints or {}


def _read_context(context: dict[str, Any], path: str | list[str]) -> tuple[Any, str]:
    tokens = path.split(".") if isinstance(path, str) else path
    value: Any = context
    for token in tokens:
        if not isinstance(token, str) or not isinstance(value, dict) or token not in value:
            raise _ExpressionIssue(
                "MISSING",
                f"context path {'.'.join(map(str, tokens))!r} is unavailable",
                constraints={"context_path": ".".join(map(str, tokens))},
            )
        value = value[token]
    return value, ".".join(map(str, tokens))


def _contains_evidence(text: str, value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    return value.strip().casefold() in text.casefold()


def _field_kind(field: str) -> str:
    name = field.casefold()
    if name in _TIME_FIELDS or any(part in name for part in ("time", "date")):
        return "TIME"
    if name in _LOCATION_FIELDS or any(part in name for part in ("address", "location", "pickup", "dropoff")):
        return "LOCATION"
    if name in _ENTITY_FIELDS or any(part in name for part in ("recipient", "contact", "identity")):
        return "ENTITY"
    if "amount" in name or "payment" in name:
        return "VALUE"
    return "ARGUMENT"


def _provenance_category(field: str) -> str | None:
    name = field.casefold()
    if "payment" in name:
        return "payment"
    if "amount" in name or "price" in name:
        return "amount"
    if any(part in name for part in ("recipient", "contact")):
        return "recipient"
    if "identity" in name or name.endswith("_id"):
        return "identity"
    if any(part in name for part in ("time", "date", "start", "end")):
        return "time"
    if any(part in name for part in ("address", "location", "pickup", "dropoff", "destination", "origin")):
        return "location"
    return None


def _time_is_explicit(value: str, text: str) -> bool:
    try:
        hour_text, minute_text = value.split(":", maxsplit=1)
        hour, minute = int(hour_text), int(minute_text)
    except (ValueError, TypeError):
        return False
    alternatives = {f"{hour:02d}:{minute:02d}", f"{hour}:{minute:02d}"}
    if minute == 0:
        alternatives.update({f"{hour} giờ", f"{hour}h"})
    return any(re.search(rf"(?<!\d){re.escape(item)}(?!\d)", text, re.IGNORECASE) for item in alternatives)


def _duration_is_explicit(hours: int | float, text: str) -> bool:
    if not float(hours).is_integer():
        return False
    amount = str(int(hours))
    patterns = (
        rf"(?<!\d){amount}\s*(?:giờ|h|hours?)(?!\w)",
        rf"(?<!\d){amount}\s* tiếng(?!\w)",
    )
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def _resolve_time(
    expression: dict[str, Any],
    context: dict[str, Any],
    transcript: str,
    field: str,
) -> tuple[Any, str]:
    base_path = expression.get("base", "context.current_time")
    if not isinstance(base_path, str) or not base_path.startswith("context."):
        raise _ExpressionIssue("INVALID", "$time base must reference context")
    base, path = _read_context(context, base_path.removeprefix("context."))
    if not isinstance(base, str):
        raise _ExpressionIssue("MISSING", "base time is unavailable", kind="TIME")
    try:
        current = datetime.fromisoformat(base.replace("Z", "+00:00"))
        relative_day = expression.get("relative_day", 0)
        elapsed_hours = expression.get("elapsed_hours")
        if elapsed_hours is not None:
            if "relative_day" in expression or not isinstance(elapsed_hours, (int, float)):
                raise ValueError("elapsed_hours must be numeric and cannot be combined with relative_day")
            if not _duration_is_explicit(elapsed_hours, transcript):
                raise _ExpressionIssue(
                    "UNSUPPORTED",
                    "elapsed duration is not explicitly supported by the request",
                    kind="TIME",
                    constraints={"elapsed_hours": elapsed_hours},
                )
            target = current + timedelta(hours=elapsed_hours)
            source_suffix = f"+{elapsed_hours}h"
        else:
            if not isinstance(relative_day, int):
                raise ValueError("relative_day must be an integer")
            text = transcript.casefold()
            day_terms = {
                0: ("hôm nay", "chiều nay", "sáng nay", "tối nay", "today", "tonight"),
                1: ("ngày mai", "mai", "tomorrow"),
                -1: ("hôm qua", "yesterday"),
            }
            if relative_day in day_terms and not any(term in text for term in day_terms[relative_day]):
                raise _ExpressionIssue(
                    "UNSUPPORTED",
                    "relative date is not supported by an explicit day reference",
                    kind="TIME",
                    constraints={"relative_day": relative_day},
                )
            target = current + timedelta(days=relative_day)
            source_suffix = f"+{relative_day}d"
        exact_time = expression.get("exact_time")
        if field.casefold() == "date" or field.casefold().endswith("_date"):
            return target.date().isoformat(), f"context.{path}{source_suffix}"
        if elapsed_hours is not None and exact_time is None:
            return target.isoformat(), f"context.{path}{source_suffix}"
        if not isinstance(exact_time, str) or not exact_time:
            raise _ExpressionIssue(
                "UNDERSPECIFIED",
                "exact time is required; a broad time period is not an exact appointment time",
                kind="TIME",
                constraints={"date": target.date().isoformat(), "period": expression.get("period")},
            )
        user_profile = context.get("user_profile", {})
        profile_text = json.dumps(user_profile, ensure_ascii=False, default=str)
        evidence_text = f"{transcript}\n{profile_text}"
        if not _time_is_explicit(exact_time, evidence_text):
            raise _ExpressionIssue(
                "UNSUPPORTED",
                "exact clock time is not supported by the request or user profile",
                kind="TIME",
                constraints={"date": target.date().isoformat(), "period": expression.get("period")},
            )
        hour_text, minute_text = exact_time.split(":", maxsplit=1)
        target = target.replace(hour=int(hour_text), minute=int(minute_text), second=0, microsecond=0)
        return target.isoformat(), f"context.{path}{source_suffix}/{exact_time}"
    except _ExpressionIssue:
        raise
    except (ValueError, TypeError) as exc:
        raise _ExpressionIssue("INVALID", f"invalid temporal expression: {exc}", kind="TIME") from exc


def _validate_grounded_location(
    value: Any,
    source: str | None,
    context: dict[str, Any],
) -> tuple[Any, str | None]:
    if source != "user" or not isinstance(value, str):
        return value, source
    normalized = value.strip().casefold()
    if normalized in _GENERIC_DESTINATIONS:
        raise _ExpressionIssue(
            "UNDERSPECIFIED",
            "a destination category is not a specific location",
            kind="LOCATION",
            constraints={"requested_destination": value},
        )
    for path in _GENERIC_LOCATION_ALIASES.get(normalized, ()):
        try:
            address, context_path = _read_context(context, path)
            if isinstance(address, str) and address.strip():
                return address, f"context.{context_path}"
        except _ExpressionIssue:
            continue
        raise _ExpressionIssue(
            "UNDERSPECIFIED",
            "a generic place such as home or work needs a concrete address from context",
            kind="LOCATION",
            constraints={"requested_location": value},
        )
    return value, source


def _resolve_value(
    value: Any,
    observations: dict[str, Any],
    context: dict[str, Any],
    transcript: str,
    field: str,
    require_provenance_for: set[str],
    strict_semantic_ready: bool,
) -> tuple[Any, str | None]:
    if isinstance(value, dict):
        if "$ref" in value:
            if set(value) != {"$ref"}:
                raise _ExpressionIssue("INVALID", "a $ref argument must contain only the $ref key")
            reference = value["$ref"]
            result = bind_value(value, observations)
            return result, f"tool:{reference.get('task_id', 'unknown')}"
        if "$context" in value:
            if set(value) != {"$context"}:
                raise _ExpressionIssue("INVALID", "a $context argument must contain only the $context key")
            result, path = _read_context(context, value["$context"])
            return result, f"context.{path}"
        if "$user" in value:
            if set(value) != {"$user"} or not isinstance(value["$user"], dict):
                raise _ExpressionIssue("INVALID", "a $user argument must contain a value and evidence")
            claim = value["$user"]
            result, evidence = claim.get("value"), claim.get("evidence")
            if not isinstance(evidence, str) or not _contains_evidence(transcript, evidence):
                raise _ExpressionIssue(
                    "UNSUPPORTED",
                    "user evidence is not present in the request",
                    kind=_field_kind(field),
                )
            if not _contains_evidence(evidence, result):
                raise _ExpressionIssue(
                    "UNSUPPORTED",
                    "the value is not supported by its user evidence",
                    kind=_field_kind(field),
                )
            return result, "user"
        if "$time" in value:
            if set(value) != {"$time"} or not isinstance(value["$time"], dict):
                raise _ExpressionIssue("INVALID", "a $time argument must contain only a temporal expression")
            result, source = _resolve_time(value["$time"], context, transcript, field)
            return result, source
        if "$need" in value:
            need = value["$need"]
            if not isinstance(need, dict):
                raise _ExpressionIssue("INVALID", "$need must contain a structured information request")
            kind = str(need.get("kind", _field_kind(field))).upper()
            constraints = need.get("constraints", {})
            if not isinstance(constraints, dict):
                constraints = {}
            if field.casefold() == "dropoff" and not constraints:
                constraints = {"query": need.get("description", "")}
            raise _ExpressionIssue(
                "UNRESOLVED",
                str(need.get("description", f"information for {field} is required")),
                kind=kind if kind in {"LOCATION", "TIME", "ENTITY", "VALUE", "FACT", "ARGUMENT"} else "ARGUMENT",
                constraints=constraints,
            )
        if "$optional_missing" in value:
            if value != {"$optional_missing": True}:
                raise _ExpressionIssue("INVALID", "$optional_missing must be true")
            return _OPTIONAL_MISSING, None
        return {
            key: _resolve_value(
                item,
                observations,
                context,
                transcript,
                f"{field}.{key}",
                require_provenance_for,
                strict_semantic_ready,
            )[0]
            for key, item in value.items()
        }, None
    if isinstance(value, (list, tuple)):
        return [
            _resolve_value(
                item,
                observations,
                context,
                transcript,
                field,
                require_provenance_for,
                strict_semantic_ready,
            )[0]
            for item in value
        ], None
    category = _provenance_category(field)
    if (
        strict_semantic_ready
        and category in require_provenance_for
        and value not in (None, "")
    ):
        context_text = json.dumps(context, ensure_ascii=False, default=str)
        kind = _field_kind(field)
        if kind == "LOCATION" and isinstance(value, str) and value.strip().casefold() in _GENERIC_DESTINATIONS:
            raise _ExpressionIssue(
                "UNDERSPECIFIED",
                "a destination category is not a specific location",
                kind="LOCATION",
                constraints={"requested_destination": value},
            )
        if kind == "LOCATION" and isinstance(value, str) and value.strip().casefold() in _GENERIC_LOCATION_ALIASES:
            for path in _GENERIC_LOCATION_ALIASES[value.strip().casefold()]:
                try:
                    result, source = _read_context(context, path)
                    if isinstance(result, str) and result.strip():
                        return result, f"context.{source}"
                except _ExpressionIssue:
                    continue
            raise _ExpressionIssue(
                "UNDERSPECIFIED",
                "a generic place such as home or work needs a concrete address from context",
                kind="LOCATION",
                constraints={"requested_location": value},
            )
        if not _contains_evidence(transcript, value) and not _contains_evidence(context_text, value):
            raise _ExpressionIssue(
                "UNSUPPORTED",
                f"critical argument {field!r} has no verifiable source",
                kind=kind,
                constraints={"field": field},
            )
        return value, "user" if _contains_evidence(transcript, value) else "context"
    return value, None


_OPTIONAL_MISSING = object()


class ResolverService:
    def __init__(
        self,
        *,
        require_provenance_for: list[str] | None = None,
        strict_semantic_ready: bool = True,
    ):
        self.require_provenance_for = set(require_provenance_for or _DEFAULT_PROVENANCE_CATEGORIES)
        self.strict_semantic_ready = strict_semantic_ready

    def resolve(
        self,
        task: PlanTask,
        observations: dict[str, Any],
        tool_spec: ToolSpec,
        *,
        context: dict[str, Any] | None = None,
        transcript: str = "",
    ) -> ResolutionResult:
        request_context = context or {}
        arguments: dict[str, Any] = {}
        provenance: dict[str, str] = {}
        issues: list[ResolutionIssue] = []
        for field, value in task.arguments.items():
            try:
                resolved, source = _resolve_value(
                    value,
                    observations,
                    request_context,
                    transcript,
                    field,
                    self.require_provenance_for,
                    self.strict_semantic_ready,
                )
                if _field_kind(field) == "LOCATION":
                    resolved, source = _validate_grounded_location(resolved, source, request_context)
            except BindingError as exc:
                self._append_issue(
                    issues,
                    task.id,
                    field,
                    exc.status,
                    str(exc),
                    _field_kind(field),
                    candidates=exc.candidates,
                )
                continue
            except _ExpressionIssue as exc:
                self._append_issue(
                    issues,
                    task.id,
                    field,
                    exc.code,
                    str(exc),
                    exc.kind,
                    constraints=exc.constraints,
                    task=task,
                    transcript=transcript,
                )
                continue
            if resolved is not _OPTIONAL_MISSING:
                arguments[field] = resolved
            if source:
                provenance[field] = source

        if issues:
            return self._issue_result(issues, arguments, provenance)

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
                self._append_issue(
                    issues,
                    task.id,
                    field,
                    "MISSING",
                    "required value is missing",
                    _field_kind(field),
                    task=task,
                    transcript=transcript,
                )
                return self._issue_result(issues, arguments, provenance)

            groups = tool_spec.parameters.get("x-one-of", [])
            if groups and not any(
                all(arguments.get(field) not in (None, "", [], {}) for field in group)
                for group in groups
            ):
                field = groups[0][0] if groups and groups[0] else "required_argument"
                person_name = next(
                    (
                        task.arguments.get(name)
                        for name in ("recipient_name", "contact_name", "person_name")
                        if isinstance(task.arguments.get(name), str) and task.arguments[name].strip()
                    ),
                    None,
                )
                if person_name:
                    self._append_issue(
                        issues,
                        task.id,
                        field,
                        "UNRESOLVED",
                        "a named recipient must be resolved to a unique allowed identity",
                        "ENTITY",
                        constraints={"query": person_name},
                        task=task,
                        transcript=transcript,
                    )
                else:
                    self._append_issue(
                        issues,
                        task.id,
                        field,
                        "MISSING",
                        "one required alternative is missing",
                        _field_kind(field),
                        task=task,
                        transcript=transcript,
                    )
                return self._issue_result(
                    issues,
                    arguments,
                    provenance,
                    status_override="NEEDS_USER" if not person_name else None,
                )
            return ResolutionResult(status="INVALID", arguments=arguments, message="; ".join(errors))
        return ResolutionResult(status="READY", arguments=arguments, provenance=provenance)

    @staticmethod
    def _append_issue(
        issues: list[ResolutionIssue],
        task_id: str,
        field: str,
        code: str,
        message: str,
        kind: str,
        *,
        constraints: dict[str, Any] | None = None,
        candidates: list[dict[str, Any]] | None = None,
        task: PlanTask | None = None,
        transcript: str = "",
    ) -> None:
        issue_id = f"{task_id}:{field}:{code.lower()}"
        normalized_kind = kind if kind in {"LOCATION", "TIME", "ENTITY", "VALUE", "FACT", "ARGUMENT"} else "ARGUMENT"
        need = None
        if code in {"MISSING", "UNDERSPECIFIED", "UNRESOLVED", "AMBIGUOUS", "NOT_FOUND", "UNSUPPORTED"}:
            query = (constraints or {}).get("query")
            need = InformationNeed(
                issue_id=issue_id,
                task_id=task_id,
                field=field,
                kind=normalized_kind,
                question=message,
                constraints=constraints or {},
                known_evidence=[{"source": "user_request", "present": bool(transcript)}] if transcript else [],
                required_precision="exact" if normalized_kind in {"LOCATION", "TIME", "ENTITY", "VALUE"} else None,
                capability_hints=(
                    ["appointment", "event"]
                    if normalized_kind in {"LOCATION", "TIME"} and any(
                        term in message.casefold() for term in ("appointment", "nha khoa", "lịch")
                    )
                    else ["contact"]
                    if normalized_kind == "ENTITY"
                    else []
                ),
                why_not_ready=message,
                needs_user_decision=code in {"AMBIGUOUS", "UNSUPPORTED"},
            )
            if query and isinstance(query, str) and task is not None:
                need.constraints.setdefault("query", query)
        issues.append(
            ResolutionIssue(
                issue_id=issue_id,
                code=code,
                field=field,
                why_not_ready=message,
                candidates=candidates or [],
                constraints=constraints or {},
                needs_user_decision=code in {"AMBIGUOUS", "UNSUPPORTED"},
                information_need=need,
            )
        )

    @staticmethod
    def _issue_result(
        issues: list[ResolutionIssue],
        arguments: dict[str, Any],
        provenance: dict[str, str],
        *,
        status_override: str | None = None,
    ) -> ResolutionResult:
        issue = issues[0]
        status = issue.code
        return ResolutionResult(
            status=status_override or status,
            arguments=arguments,
            field=issue.field,
            candidates=issue.candidates,
            message=issue.why_not_ready,
            issues=issues,
            provenance=provenance,
        )
