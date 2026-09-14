"""The gate over the whole project: real basedpyright on a shadow tree of a small package. Skipped
where basedpyright is not installed."""
import json
from pathlib import Path

import pytest

from devcompanion import config
from devcompanion.canon import sha
from devcompanion.engine import Engine
from devcompanion.fix import check, propose
from devcompanion.fix.project import Project
from devcompanion.llm.client import Reply
from devcompanion.observe.events import Event
from devcompanion.present.problems import group

BINARY = check.checker()
pytestmark = pytest.mark.skipif(BINARY is None, reason="basedpyright not installed")

MODELS = "class User:\n    def __init__(self, name: str) -> None:\n        self.name = name\n"
VIEWS = 'from .models import User\n\n\ndef greet(user: User) -> str:\n    return "hi " + user.nme\n'
PATCH = '<<<<<<< SEARCH\n    return "hi " + user.nme\n=======\n    return "hi " + user.name\n>>>>>>> REPLACE'


@pytest.fixture
def root(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "pkg").mkdir(parents=True)
    (project / "pkg/__init__.py").write_text("")
    (project / "pkg/models.py").write_text(MODELS)
    (project / "pkg/views.py").write_text(VIEWS)
    return project


def errors(items: list[dict]) -> list[dict]:
    return [d for d in items if d["severity"] == "error"]


def asking(text):
    return lambda spec, system, user, timeout_s: Reply(text, "ok")


def never(spec, system, user, timeout_s):
    raise AssertionError("the model must not be asked")


def test_the_gate_sees_through_imports_only_when_given_the_project(root):
    alone = check.diagnose({"pkg/views.py": VIEWS}, BINARY)["pkg/views.py"]
    whole = check.diagnose({"pkg/views.py": VIEWS}, BINARY, project=Project(root))["pkg/views.py"]
    assert "reportAttributeAccessIssue" not in {d["code"] for d in alone}
    assert [d["code"] for d in errors(whole)] == ["reportAttributeAccessIssue"]


def test_an_unsaved_buffer_elsewhere_is_what_the_gate_checks_against(root):
    buffer = MODELS.replace("self.name", "self.nme")
    whole = check.diagnose({"pkg/views.py": VIEWS}, BINARY,
                           project=Project(root, overlay={"pkg/models.py": buffer}))["pkg/views.py"]
    assert errors(whole) == []
    assert (root / "pkg/models.py").read_text() == MODELS


def test_a_fix_for_a_problem_only_the_project_shows_is_checked(root, tmp_path):
    cfg = config.load(root, machine=tmp_path / "absent.toml")
    problems = group(errors(check.diagnose({"pkg/views.py": VIEWS}, BINARY, project=Project(root))["pkg/views.py"]))
    [fixed] = propose.propose(cfg, "pkg/views.py", VIEWS, problems, ask=asking(PATCH), binary=BINARY,
                              project=Project(root))
    assert fixed.outcome == "checked" and fixed.edits == [{"line": 5, "end_line": 6, "text": '    return "hi " + user.name\n'}]
    [alone] = propose.propose(cfg, "pkg/views.py", VIEWS, problems, ask=never, binary=BINARY)
    assert alone.outcome == "not_visible"


def test_the_engine_checks_fixes_against_the_project_with_its_unsaved_buffers(root, tmp_path):
    eng = Engine(root, run_tests=False, log=lambda _: None, ask=asking(PATCH),
                 config=config.load(root, machine=tmp_path / "absent.toml"))
    for name in ("pkg/models.py", "pkg/views.py"):
        eng.handle_event(Event(kind="buffer_saved", path=name))
    eng.sched.drain(wait=False)
    items = errors(check.diagnose({"pkg/views.py": VIEWS}, BINARY, project=Project(root))["pkg/views.py"])
    eng.handle_event(Event(kind="diagnostics", path="pkg/views.py", source="nvim", session="s1", items=items))
    eng.sched.drain(wait=False)

    published = [json.loads(l) for l in (root / ".companion/findings.jsonl").read_text().splitlines()]
    [problem] = [f for f in published if f["kind"] == "diagnostic_context"]
    assert problem["fix"]["verdict"] == "checked"
    assert problem["fix"]["depends_on"] == {"pkg/views.py": sha(VIEWS.encode())}
    assert (root / "pkg/views.py").read_text() == VIEWS
