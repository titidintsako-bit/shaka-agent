"""Tests for Shaka eval harness."""

from shaka.eval_runtime import EvalRunner


def test_eval_runner_passes_core_checks(tmp_path):
    result = EvalRunner(str(tmp_path)).run()

    assert result["failed"] == 0
    assert result["passed"] >= 4
