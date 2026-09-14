"""util.session_id() has to differ across Neovim instances, or a watermark keyed on
(session, editor_seq) rejects everything a restarted editor sends. This is the bug
docs/intake-watermark.md documents: LuaJIT does not seed math.random, so every instance on a
machine returned the same id. A single-process Lua assertion cannot catch that -- the failure
only appears across processes, so this drives two real headless Neovim instances, exactly how
the bug was originally found."""
import subprocess
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def session_id() -> str:
    p = subprocess.run(
        ["nvim", "--headless", "-u", "NONE", "-n", "-i", "NONE",
         "--cmd", f"set rtp+={PROJECT}/nvim",
         "-c", 'lua io.write(require("companion.util").session_id())',
         "-c", "qa!"],
        capture_output=True, text=True, timeout=15,
    )
    assert p.returncode == 0, p.stderr
    return p.stdout.strip()


def test_two_neovim_instances_get_different_session_ids():
    ids = {session_id() for _ in range(3)}
    assert len(ids) == 3, f"every instance should be unique; got {ids}"
