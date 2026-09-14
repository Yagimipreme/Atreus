import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from devcompanion import instance

SRC = Path(__file__).resolve().parents[1] / "src"


def test_a_second_claim_on_the_same_workspace_is_refused_and_names_the_holder(tmp_path):
    first = instance.claim(tmp_path)
    with pytest.raises(instance.AlreadyRunning) as refused:
        instance.claim(tmp_path)
    assert refused.value.holder == str(os.getpid())
    first.close()
    instance.claim(tmp_path).close()          # released with the file, as on exit


def test_a_lock_left_by_a_dead_process_does_not_block(tmp_path):
    (tmp_path / "engine.lock").write_text("999999\n")   # a pid file alone would read as held
    instance.claim(tmp_path).close()


def test_a_second_watch_refuses_to_start_while_the_first_runs(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    command = [sys.executable, "-m", "devcompanion.cli", "--root", str(tmp_path), "--no-tests", "watch"]
    first = subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        lock = tmp_path / ".companion/engine.lock"
        deadline = time.time() + 20
        while time.time() < deadline and not (lock.exists() and lock.read_text().strip() == str(first.pid)):
            time.sleep(0.1)
        assert lock.read_text().strip() == str(first.pid), "the first engine never took the workspace"
        engine_json = (tmp_path / ".companion/engine.json").read_bytes()

        second = subprocess.run(command, env=env, capture_output=True, text=True, timeout=20)
        assert second.returncode == 1
        assert f"another engine (pid {first.pid})" in second.stderr
        assert first.poll() is None, "the first engine must keep running"
        assert b'"pid": %d' % first.pid in engine_json or str(first.pid).encode() in \
            (tmp_path / ".companion/engine.json").read_bytes(), "the second must not have taken engine.json"
    finally:
        first.terminate()
        first.wait(timeout=20)
