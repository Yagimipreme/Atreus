"""Proposing checked fixes for a file's problems, against real basedpyright and a stand-in model.
Skipped where basedpyright is not installed."""
import pytest

from devcompanion import config
from devcompanion.fix import check, propose
from devcompanion.llm.client import Reply
from devcompanion.present.problems import group

BINARY = check.checker()
pytestmark = pytest.mark.skipif(BINARY is None, reason="basedpyright not installed")

BROKEN = 'def fields(line: str) -> list[str]:\n    """Comma-separated fields."""\n    return line.split(3)\n'
PATH = "pkg/fields.py"


def replacing(line: str) -> str:
    return f"<<<<<<< SEARCH\n    return line.split(3)\n=======\n{line}\n>>>>>>> REPLACE"


def asking(text, status="ok"):
    return lambda spec, system, user, timeout_s: Reply(text, status)


def never(spec, system, user, timeout_s):
    raise AssertionError("the model must not be asked")


@pytest.fixture(scope="module")
def problems():
    return group([d for d in check.diagnose({PATH: BROKEN}, BINARY)[PATH] if d["severity"] == "error"])


@pytest.fixture
def cfg(tmp_path):
    return config.load(tmp_path, machine=tmp_path / "absent.toml")


def test_a_checked_proposal_comes_back_as_line_edits_and_a_diff(cfg, problems):
    [p] = propose.propose(cfg, PATH, BROKEN, problems, ask=asking(replacing('    return line.split(",")')), binary=BINARY)
    assert (p.outcome, p.profile, p.warnings) == ("checked", "local-qwen3-coder", [])
    assert p.edits == [{"line": 3, "end_line": 4, "text": '    return line.split(",")\n'}]
    assert '+    return line.split(",")' in p.diff and p.problem == problems[0].key


def test_a_new_warning_rides_along_with_the_check(cfg, problems):
    [p] = propose.propose(cfg, PATH, BROKEN, problems, binary=BINARY,
                          ask=asking(replacing('    unused = 1\n    return line.split(",")')))
    assert p.outcome == "checked" and len(p.warnings) == 1 and "unused" in p.warnings[0]


def test_a_refused_proposal_says_why_and_carries_no_edit(cfg, problems):
    [p] = propose.propose(cfg, PATH, BROKEN, problems, ask=asking(replacing("    return line.split(4)")), binary=BINARY)
    assert p.outcome == "refused" and p.detail.startswith("unresolved") and p.edits == [] and not p.transient


def test_no_answer_is_transient(cfg, problems):
    [p] = propose.propose(cfg, PATH, BROKEN, problems, ask=asking(None, "unavailable"), binary=BINARY)
    assert p.outcome == "unavailable" and p.transient


def test_a_problem_the_single_file_checker_cannot_see_is_never_sent_to_a_model(cfg):
    editor_only = group([{"line": 1, "col": 1, "code": "reportMissingImports", "severity": "error",
                          "message": 'Import "shop.models" could not be resolved'}])
    [p] = propose.propose(cfg, PATH, BROKEN, editor_only, ask=never, binary=BINARY)
    assert p.outcome == "not_visible" and not p.transient


TWO = BROKEN + "\n\ndef total(values: list[int]) -> int:\n    return sum(values) + None\n"
SPLIT = '<<<<<<< SEARCH\n    return line.split(3)\n=======\n    return line.split(",")\n>>>>>>> REPLACE'
SUM = "<<<<<<< SEARCH\n    return sum(values) + None\n=======\n    return sum(values)\n>>>>>>> REPLACE"


def two_problems():
    return group([d for d in check.diagnose({PATH: TWO}, BINARY)[PATH] if d["severity"] == "error"])


def test_a_fix_that_also_resolves_a_later_problem_is_one_fix_and_the_later_problem_is_not_asked(cfg):
    calls = []

    def ask(spec, system, user, timeout_s):
        calls.append(user)
        return Reply(f"{SPLIT}\n{SUM}", "ok")

    problems = two_problems()
    first, second = propose.propose(cfg, PATH, TWO, problems, ask=ask, binary=BINARY)
    assert len(calls) == 1, "the second problem was already resolved by the first fix"
    assert (first.outcome, second.outcome) == ("checked", "checked") and first.edits == second.edits
    assert first.fix_id == second.fix_id != "" and first.covers == second.covers == [3, 7]
    assert (second.problem, second.line) == (problems[1].key, 7)


def test_fixes_for_different_problems_stay_separate(cfg):
    def ask(spec, system, user, timeout_s):
        return Reply(SPLIT if "split" in user.split("Code:")[0] else SUM, "ok")

    first, second = propose.propose(cfg, PATH, TWO, two_problems(), ask=ask, binary=BINARY)
    assert (first.outcome, second.outcome) == ("checked", "checked")
    assert first.fix_id != second.fix_id and (first.covers, second.covers) == ([3], [7])


def test_edits_are_line_ranges_including_pure_insertions():
    assert propose.edits("a\nb\nc\n", "a\nB\nc\n") == [{"line": 2, "end_line": 3, "text": "B\n"}]
    assert propose.edits("a\nc\n", "a\nb\nc\n") == [{"line": 2, "end_line": 2, "text": "b\n"}]
