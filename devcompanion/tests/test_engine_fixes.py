"""Checked fixes through the real engine: a saved file's errors -> a proposal from a stand-in model
-> the real gate -> a `fix` on the published problem. Skipped where basedpyright is not installed."""
import json

import pytest

from devcompanion import config
from devcompanion.canon import sha
from devcompanion.engine import Engine
from devcompanion.fix import check
from devcompanion.llm.client import Reply
from devcompanion.observe.events import Event

BINARY = check.checker()
pytestmark = pytest.mark.skipif(BINARY is None, reason="basedpyright not installed")

BROKEN = 'def fields(line: str) -> list[str]:\n    """Comma-separated fields."""\n    return line.split(3)\n'
FIXED = BROKEN.replace("split(3)", 'split(",")')
PATCH = '<<<<<<< SEARCH\n    return line.split(3)\n=======\n    return line.split(",")\n>>>>>>> REPLACE'


def editor_errors(text: str) -> list[dict]:
    """What the editor's language server sends for this text."""
    return [d for d in check.diagnose({"fields.py": text}, BINARY)["fields.py"] if d["severity"] == "error"]


def published(root) -> list[dict]:
    return [json.loads(line) for line in (root / ".companion/findings.jsonl").read_text().splitlines()]


def problems(root) -> list[dict]:
    return [f for f in published(root) if f["kind"] == "diagnostic_context"]


def diagnostics(items) -> Event:
    return Event(kind="diagnostics", path="fields.py", source="nvim", session="s1", items=items)


@pytest.fixture
def engine(tmp_path):
    (tmp_path / "fields.py").write_text(BROKEN)
    asked: list[str] = []

    def ask(spec, system, user, timeout_s):
        asked.append(user)
        return Reply(PATCH, "ok")

    cfg = config.load(tmp_path, machine=tmp_path / "absent.toml")
    eng = Engine(tmp_path, run_tests=False, log=lambda _: None, config=cfg, ask=ask)
    eng.handle_event(Event(kind="buffer_saved", path="fields.py"))
    eng.sched.drain(wait=False)
    return eng, tmp_path, asked


def test_a_saved_file_with_an_error_gets_a_checked_fix_on_its_problem(engine):
    eng, root, asked = engine
    eng.handle_event(diagnostics(editor_errors(BROKEN)))
    eng.sched.drain(wait=False)

    [problem] = problems(root)
    fix = problem["fix"]
    assert fix["verdict"] == "checked" and fix["warnings"] == [] and fix["profile"] == "local-qwen3-coder"
    assert fix["edits"] == [{"line": 3, "end_line": 4, "text": '    return line.split(",")\n'}]
    assert fix["depends_on"] == {"fields.py": sha(BROKEN.encode())}
    assert (root / "fields.py").read_text() == BROKEN, "the engine never writes a developer file"
    assert len(asked) == 1 and "line.split(3)" in asked[0]


def test_one_fix_for_two_problems_is_published_on_both_as_the_same_fix(tmp_path):
    two = BROKEN + "\n\ndef total(values: list[int]) -> int:\n    return sum(values) + None\n"
    both = PATCH + "\n<<<<<<< SEARCH\n    return sum(values) + None\n=======\n    return sum(values)\n>>>>>>> REPLACE"
    (tmp_path / "fields.py").write_text(two)
    calls = []

    def ask(spec, system, user, timeout_s):
        calls.append(user)
        return Reply(both, "ok")

    eng = Engine(tmp_path, run_tests=False, log=lambda _: None, ask=ask,
                 config=config.load(tmp_path, machine=tmp_path / "absent.toml"))
    eng.handle_event(Event(kind="buffer_saved", path="fields.py"))
    eng.sched.drain(wait=False)
    eng.handle_event(diagnostics(editor_errors(two)))
    eng.sched.drain(wait=False)

    fixes = [p["fix"] for p in problems(tmp_path)]
    assert len(fixes) == 2 and len(calls) == 1
    assert fixes[0]["id"] == fixes[1]["id"] and fixes[0]["covers"] == fixes[1]["covers"] == [3, 7]


def test_the_same_revision_is_not_asked_twice(engine):
    eng, _, asked = engine
    for _ in range(2):
        eng.handle_event(diagnostics(editor_errors(BROKEN)))
        eng.sched.drain(wait=False)
    assert len(asked) == 1


def test_an_unsaved_buffer_gets_no_fix(engine):
    eng, root, asked = engine
    draft = BROKEN + "\n"
    eng.handle_event(Event(kind="buffer_changed", path="fields.py", source="nvim", session="s1", text=draft,
                           text_sha=sha(draft.encode()), dirty=True, fileformat="unix", eol=True))
    eng.handle_event(diagnostics(editor_errors(draft)))
    eng.sched.drain(wait=False)
    assert asked == [] and "fix" not in problems(root)[0]


def test_saving_other_code_retires_the_fix(engine):
    eng, root, _ = engine
    eng.handle_event(diagnostics(editor_errors(BROKEN)))
    eng.sched.drain(wait=False)
    assert "fix" in problems(root)[0]

    (root / "fields.py").write_text(FIXED)
    eng.handle_event(Event(kind="buffer_saved", path="fields.py"))
    eng.sched.drain(wait=False)
    eng.handle_event(diagnostics([]))
    assert problems(root) == []
    assert eng.evid.state[next(k for k in eng.evid.state if k.startswith("fix:"))]["status"] == "stale"


def test_an_action_result_is_logged_and_changes_nothing(engine):
    eng, root, _ = engine
    eng.handle_event(diagnostics(editor_errors(BROKEN)))
    eng.sched.drain(wait=False)
    before = json.dumps(eng.evid.state, sort_keys=True)
    eng.handle_event(Event(kind="action_result", source="nvim", session="s1", finding_id="f-1", status="applied",
                           path="fields.py", extra={"action": "fix"}))
    eng.sched.drain(wait=False)
    assert json.dumps(eng.evid.state, sort_keys=True) == before
    assert (root / "fields.py").read_text() == BROKEN
    assert "action_result" in (root / ".companion/events.jsonl").read_text()


def test_no_model_answer_is_not_recorded_and_the_next_save_asks_again(tmp_path):
    (tmp_path / "fields.py").write_text(BROKEN)
    calls = []

    def down(spec, system, user, timeout_s):
        calls.append(user)
        return Reply(None, "unavailable")

    eng = Engine(tmp_path, run_tests=False, log=lambda _: None,
                 config=config.load(tmp_path, machine=tmp_path / "absent.toml"), ask=down)
    eng.handle_event(Event(kind="buffer_saved", path="fields.py"))
    eng.sched.drain(wait=False)
    for _ in range(2):
        eng.handle_event(diagnostics(editor_errors(BROKEN)))
        eng.sched.drain(wait=False)
    assert len(calls) == 2 and not any(k.startswith("fix:") for k in eng.evid.state)


def test_without_the_model_tier_nothing_is_proposed(tmp_path):
    (tmp_path / "fields.py").write_text(BROKEN)
    eng = Engine(tmp_path, run_tests=False, log=lambda _: None)
    eng.handle_event(Event(kind="buffer_saved", path="fields.py"))
    eng.handle_event(diagnostics(editor_errors(BROKEN)))
    eng.sched.drain(wait=False)
    assert "fix" not in problems(tmp_path)[0] and eng.sched.stats["submitted"] == 1
