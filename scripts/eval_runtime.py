"""Run Runtime's fixed, model-free benchmark fixtures."""

from pathlib import Path

import pytest

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    tests = root / "modules" / "runtime" / "tests"
    adaptive = root / "tests" / "test_adaptive_repair.py"
    integration = root / "tests" / "test_runtime_resolver.py"
    raise SystemExit(pytest.main(["-q", str(tests), str(adaptive), str(integration)]))
