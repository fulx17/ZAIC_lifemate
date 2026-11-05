import pytest
from pydantic import ValidationError

from core.contracts import PlanCondition, PlanGoal, PlanTask, TaskPlan


def _plan(*, when=None, arguments=None, depends_on=()):
    return TaskPlan(
        goals=[PlanGoal(id="g1", description="goal")],
        tasks=[
            PlanTask(id="lookup", goal_id="g1", tool="contacts.search"),
            PlanTask(
                id="action",
                goal_id="g1",
                tool="phone.call",
                arguments=arguments or {},
                depends_on=depends_on,
                when=when,
            ),
        ],
    )


def test_v2_plan_rejects_dependency_cycles_and_unknown_references() -> None:
    with pytest.raises(ValidationError, match="cycle"):
        TaskPlan(
            goals=[PlanGoal(id="g1", description="goal")],
            tasks=[
                PlanTask(id="a", goal_id="g1", tool="a", depends_on=("b",)),
                PlanTask(id="b", goal_id="g1", tool="b", depends_on=("a",)),
            ],
        )

    with pytest.raises(ValidationError, match="dependency"):
        _plan(arguments={"contact_id": {"$ref": {"task_id": "lookup", "path": ["contacts"], "field": "id"}}})


def test_v2_plan_requires_references_and_conditions_to_depend_on_source() -> None:
    with pytest.raises(ValidationError, match="condition source"):
        _plan(when=PlanCondition(task_id="lookup", path=["rain"], equals=True))

    plan = _plan(
        when=PlanCondition(task_id="lookup", path=["rain"], equals=True),
        arguments={"contact_id": {"$ref": {"task_id": "lookup", "path": ["contacts"], "field": "id"}}},
        depends_on=("lookup",),
    )
    assert plan.schema_version == "2.0"


def test_validated_plan_data_is_immutable() -> None:
    plan = _plan(
        arguments={"contact_id": {"$ref": {"task_id": "lookup", "path": ["contacts"], "field": "id"}}},
        depends_on=("lookup",),
    )
    with pytest.raises(ValidationError):
        plan.schema_version = "1.0"
    with pytest.raises(TypeError, match="immutable"):
        plan.tasks[1].arguments["contact_id"] = "invented"
