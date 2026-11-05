import pytest

from core.contracts import AgentRequest, PlanGoal, PlanTask, ToolSpec
from core.llm import BudgetedLLMClient, MockLLMClient
from modules.planner.service import PlanInvalidError, SingleShotPlanner


def test_qwen_planner_makes_exactly_one_nonrepairing_call() -> None:
    raw_llm = MockLLMClient(
        {
            "plan": {
                "schema_version": "2.0",
                "goals": [{"id": "g1", "description": "Check weather"}],
                "tasks": [
                    {
                        "id": "t1",
                        "goal_id": "g1",
                        "tool": "weather.get_forecast",
                        "arguments": {"date": "2026-11-29"},
                    }
                ],
            }
        }
    )
    llm = BudgetedLLMClient(raw_llm, max_calls=1)
    planner = SingleShotPlanner(llm)
    request = AgentRequest(sample_id="s1", transcript="Mai có mưa không?", context={})
    candidates = [ToolSpec(name="weather.get_forecast")]

    plan = planner.generate_plan(request, candidates)

    assert plan.tasks[0].tool == "weather.get_forecast"
    assert len(raw_llm.calls) == 1
    assert raw_llm.call_settings[0]["max_json_repair"] == 0
    assert llm.calls_used == 1


def test_invalid_plan_does_not_trigger_a_second_call() -> None:
    invalid = {
        "schema_version": "2.0",
        "goals": [PlanGoal(id="g1", description="goal").model_dump()],
        "tasks": [
            PlanTask(id="a", goal_id="g1", tool="weather.get_forecast", depends_on=("b",)).model_dump(),
            PlanTask(id="b", goal_id="g1", tool="weather.get_forecast", depends_on=("a",)).model_dump(),
        ],
    }
    raw_llm = MockLLMClient({"plan": invalid})
    planner = SingleShotPlanner(BudgetedLLMClient(raw_llm, max_calls=1))
    with pytest.raises(PlanInvalidError, match="cycle"):
        planner.generate_plan(
            AgentRequest(sample_id="s1", transcript="weather", context={}),
            [ToolSpec(name="weather.get_forecast")],
        )
    assert len(raw_llm.calls) == 1
