"""Run Resolver's fixed, model-free benchmark fixtures."""

from pathlib import Path

import pytest

if __name__ == "__main__":
    tests = Path(__file__).resolve().parents[1] / "modules" / "resolver" / "tests"
    raise SystemExit(pytest.main(["-q", str(tests)]))
