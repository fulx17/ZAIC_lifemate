from core.contracts import PlanTask, ToolSpec
from modules.resolver.service import ResolverService


def test_reference_binds_a_unique_matched_entity() -> None:
    task = PlanTask(
        id="call",
        goal_id="g1",
        tool="phone.call",
        arguments={
            "contact_id": {
                "$ref": {
                    "task_id": "search",
                    "path": ["contacts"],
                    "match": {"name": "Lan"},
                    "field": "id",
                    "require_unique": True,
                }
            }
        },
        depends_on=("search",),
    )
    resolved = ResolverService().resolve(
        task,
        {"search": {"contacts": [{"id": "c1", "name": "Lan"}]}},
        ToolSpec(
            name="phone.call",
            parameters={"properties": {"contact_id": {"type": "string"}}, "required": ["contact_id"]},
        ),
    )
    assert resolved.status == "READY"
    assert resolved.arguments == {"contact_id": "c1"}


def test_reference_never_selects_first_ambiguous_match() -> None:
    task = PlanTask(
        id="call",
        goal_id="g1",
        tool="phone.call",
        arguments={
            "contact_id": {
                "$ref": {
                    "task_id": "search",
                    "path": ["contacts"],
                    "match": {"name": "Lan"},
                    "field": "id",
                    "require_unique": True,
                }
            }
        },
        depends_on=("search",),
    )
    resolved = ResolverService().resolve(
        task,
        {"search": {"contacts": [{"id": "c1", "name": "Lan"}, {"id": "c2", "name": "Lan"}]}},
        ToolSpec(name="phone.call", parameters={"required": ["contact_id"]}),
    )
    assert resolved.status == "AMBIGUOUS"
    assert len(resolved.candidates) == 2


def test_schema_one_of_requires_user_information() -> None:
    task = PlanTask(id="send", goal_id="g1", tool="sms.send", arguments={"content": "Đến muộn"})
    resolved = ResolverService().resolve(
        task,
        {},
        ToolSpec(
            name="sms.send",
            parameters={
                "properties": {"content": {"type": "string"}, "contact_id": {"type": "string"}},
                "required": ["content"],
                "x-one-of": [["contact_id"]],
            },
        ),
    )
    assert resolved.status == "NEEDS_USER"
    assert resolved.field == "contact_id"
