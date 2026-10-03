import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def _run_help(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / script), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_migrate_joint_ledger_runs_directly():
    result = _run_help("scripts/migrate_joint_ledger.py")
    assert result.returncode == 0, result.stderr
    assert "Migrate legacy joint_ledger.csv" in result.stdout


def test_build_selfwealth_performance_runs_directly():
    result = _run_help("scripts/build_selfwealth_performance.py")
    assert result.returncode == 0, result.stderr
    assert "Build SelfWealth performance cache" in result.stdout
