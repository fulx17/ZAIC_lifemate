import pytest
from pydantic import BaseModel

from core.errors import BudgetExceededError
from core.llm import BudgetedLLMClient, MockLLMClient


class Output(BaseModel):
    value: str


def test_llm_budget_counts_shared_client_calls_and_resets_per_request() -> None:
    client = MockLLMClient({"test": {"value": "ok"}})
    budget = BudgetedLLMClient(client, max_calls=1)
    assert budget.generate_json("test", {}, Output).value == "ok"
    with pytest.raises(BudgetExceededError):
        budget.generate_json("test", {}, Output)
    budget.reset()
    assert budget.generate_json("test", {}, Output).value == "ok"
