from pathlib import Path

import pytest

from app.environment import OfficialEnvironment


def test_official_adapter_read_only_introspection_for_both_splits() -> None:
    root = Path(__file__).resolve().parents[1] / "train+public_test" / "train+public_test"
    if not (root / "train" / "train_environment").is_dir():
        pytest.skip("local kit data is not present")
    for split, sample_id in (("train", "train_0001"), ("public_test", "public_0002")):
        environment = OfficialEnvironment(root, split, sample_id)
        names = {tool.name for tool in environment.list_available_tools()}
        assert names
        assert "sys.ask_missing_info" in names
        assert len(environment.get_state_hash()) == 64
        assert environment.get_tool_calls() == []
