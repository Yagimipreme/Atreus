"""Run the tests that mention a function, if pytest is available. Tool-unavailable is ordinary."""
from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TestResult:
    status: str          # passed | failed | unavailable | timeout | none
    summary: str
    files: list[str]
    output_tail: str = ""


def _pytest_cmd() -> list[str] | None:
    r = subprocess.run([sys.executable, "-c", "import pytest"], capture_output=True)
    if r.returncode == 0:
        return [sys.executable, "-m", "pytest"]
    if shutil.which("pytest"):
        return ["pytest"]
    return None


def run_for(root: Path, names: list[str], timeout_s: float = 60) -> TestResult:
    def mentions(p: Path) -> bool:
        b = p.read_bytes()
        return any(n.encode() in b for n in names)
    files = sorted({str(p) for pat in ("test_*.py", "*_test.py") for p in root.rglob(pat)
                    if ".companion" not in p.parts and mentions(p)})
    if not files:
        return TestResult("none", f"no test file mentions {', '.join(names)}", [])
    cmd = _pytest_cmd()
    if cmd is None:
        return TestResult("unavailable", "pytest not importable in this interpreter", files)
    try:
        r = subprocess.run(cmd + ["-q", "-x", "--no-header", "-p", "no:cacheprovider", *files],
                           cwd=root, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return TestResult("timeout", f"pytest exceeded {timeout_s}s", files)
    tail = "\n".join((r.stdout + r.stderr).strip().splitlines()[-12:])
    last = tail.splitlines()[-1] if tail else ""
    return TestResult("passed" if r.returncode == 0 else "failed", last, files, tail)
