"""Basic tests for Shaka CLI and core functionality."""
import subprocess
import sys


def test_cli_import():
    """Test that we can import the CLI module."""
    try:
        from shaka.cli import cli
        assert cli is not None
    except ImportError as e:
        raise AssertionError(f"Failed to import shaka.cli: {e}")


def test_doctor_command():
    """Test that 'shaka doctor' runs without error."""
    result = subprocess.run(
        [sys.executable, "-m", "shaka.cli", "doctor"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    # Doctor should exit with 0 (success) or at least not crash
    assert result.returncode == 0, f"doctor failed: {result.stderr}"
    # Check for expected output (language-agnostic)
    assert ("SHAKA SYSTEM CHECK" in result.stdout or "SHAKA UPHANDO LWEZIMSO" in result.stdout)
    assert "[Config]" in result.stdout
    assert "[Skills]" in result.stdout
    assert "[Memory]" in result.stdout
    assert "[Data]" in result.stdout
    assert "[Python]" in result.stdout


if __name__ == "__main__":
    test_cli_import()
    test_doctor_command()
    print("All tests passed.")