"""The committed version is the baseline for a file seen for the first time.

`git show HEAD:<path>` resolves from the repository root, not from the directory `git -C`
points at, so a workspace nested inside its repository needs that prefix prepended.

Found by running the engine against this project after it was committed into a repository
rooted a level above it: every file read as first-seen, nothing was ever compared, and the
companion said nothing at all. Every fixture in the integration harness is its own repository
with the workspace at its root, which is exactly why nothing caught it.
"""
import subprocess

import pytest

from devcompanion.engine import Engine
from devcompanion.observe.events import Event

SAVED = "def add(a, b):\n    return a + b\n"
BROKEN = "def add(a, b, carry):\n    return a + b + carry\n"
CLIENT = "from calc import add\n\ndef total():\n    return add(1, 2)\n"


def commit(repo):
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@l",
                    "commit", "-qm", "baseline"], cwd=repo, check=True)


@pytest.fixture(params=["workspace is the repo root", "workspace is nested in the repo"])
def workspace(request, tmp_path):
    """The same project, committed two ways. The engine must behave identically."""
    repo = tmp_path / "repo"
    root = repo if request.param.startswith("workspace is the repo root") else repo / "sub" / "project"
    root.mkdir(parents=True)
    (root / "calc.py").write_text(SAVED)
    (root / "client.py").write_text(CLIENT)
    commit(repo)
    return root


def test_a_committed_file_is_compared_against_head_not_treated_as_new(workspace):
    eng = Engine(workspace, run_tests=False, log=lambda _: None)
    (workspace / "calc.py").write_text(BROKEN)
    eng.handle_event(Event(kind="buffer_saved", path="calc.py"))
    eng.sched.drain(wait=False)

    rec = eng.evid.state.get("signature_change:calc.py:add")
    assert rec is not None, "no baseline seeded, so the change was invisible"
    assert rec["claim"].startswith("1 call site(s): 1 break")
    assert "file:calc.py" not in eng.evid.state, "must not have been dismissed as first-seen"


def test_the_prefix_is_empty_at_the_repo_root_and_set_below_it(tmp_path):
    repo = tmp_path / "repo"
    nested = repo / "sub" / "project"
    nested.mkdir(parents=True)
    (nested / "calc.py").write_text(SAVED)
    commit(repo)
    assert Engine(repo, run_tests=False, log=lambda _: None)._git_prefix() == ""
    assert Engine(nested, run_tests=False, log=lambda _: None)._git_prefix() == "sub/project/"


def test_a_workspace_with_no_repository_still_works(tmp_path):
    """No git is an ordinary state: first sight of a file is simply its own baseline."""
    (tmp_path / "calc.py").write_text(SAVED)
    eng = Engine(tmp_path, run_tests=False, log=lambda _: None)
    assert eng._git_prefix() == ""
    eng.handle_event(Event(kind="buffer_saved", path="calc.py"))
    eng.sched.drain(wait=False)
    assert eng.evid.state["file:calc.py"]["kind"] == "noop"
