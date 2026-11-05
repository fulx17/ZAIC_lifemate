"""Run Runtime's fixed, model-free benchmark fixtures."""

from pathlib import Path

import pytest

if __name__ == "__main__":
    tests = Path(__file__).resolve().parents[1] / "modules" / "runtime" / "tests"
    integration = Path(__file__).resolve().parents[1] / "tests" / "test_runtime_resolver.py"
    raise SystemExit(pytest.main(["-q", str(tests), str(integration)]))
