"""The checker's verdict, against real basedpyright output. Skipped where basedpyright is not
installed: these assert what the tool says, and a stand-in would only agree with itself."""
import pytest

from devcompanion.fix import check

BINARY = check.checker()
pytestmark = pytest.mark.skipif(BINARY is None, reason="basedpyright not installed")

WORKING = 'def fields(line: str) -> list[str]:\n    """Comma-separated fields."""\n    return line.split(",")\n'
BROKEN = WORKING.replace('line.split(",")', "line.split(3)")
PATH = "fields.py"


@pytest.fixture(scope="module")
def case():
    got = check.diagnose({"working.py": WORKING, "broken.py": BROKEN}, BINARY)
    before = got["broken.py"]
    return before, check.introduced(got["working.py"], before)


def judge(case, reply: str) -> check.Verdict:
    before, targets = case
    return check.judge(PATH, BROKEN, reply, targets, before, BINARY)


def replacing(line: str) -> str:
    return f"<<<<<<< SEARCH\n    return line.split(3)\n=======\n{line}\n>>>>>>> REPLACE"


def test_the_mutation_is_what_the_checker_reports(case):
    _, targets = case
    assert "reportArgumentType" in {t["code"] for t in targets}
    assert all(t["line"] == 3 for t in targets)


def test_the_intended_fix_is_checked(case):
    assert judge(case, replacing('    return line.split(",")')).outcome == "checked"


def test_a_type_correct_fix_is_checked_even_when_it_is_not_what_was_meant(case):
    # The limit of the whole tier, pinned: intent is not the checker's to judge.
    assert judge(case, replacing('    return line.split("3")')).outcome == "checked"


def test_silencing_the_checker_is_refused(case):
    assert judge(case, replacing("    return line.split(3)  # type: ignore")).outcome == "suppressed"


def test_a_fix_that_leaves_the_diagnostic_is_unresolved(case):
    assert judge(case, replacing("    return line.split(4)")).outcome == "unresolved"


def test_a_fix_that_breaks_something_else_is_refused(case):
    verdict = judge(case, replacing("    return line.split(sep)"))
    assert verdict.outcome == "new_diagnostics"
    assert any("sep" in d["message"] for d in verdict.new)


def test_a_fix_that_adds_only_a_warning_is_checked_and_carries_the_warning(case):
    # Noted, not refused: the gate compares against the broken code, so a correct fix can carry a
    # warning the broken code never reached.
    verdict = judge(case, replacing('    unused = 1\n    return line.split(",")'))
    assert verdict.outcome == "checked"
    assert [d["code"] for d in verdict.warnings] == ["reportUnusedVariable"]
    assert verdict.new == []


def test_unparsable_and_misplaced_replies_never_reach_the_checker(case):
    assert judge(case, replacing('    return line.split(","')).outcome == "unparsable"
    assert judge(case, "Use a string.").outcome == "no_patch"
