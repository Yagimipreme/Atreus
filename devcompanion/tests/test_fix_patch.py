"""A model reply becomes an edit only when it says exactly where; otherwise it is refused, with
the reason, so an evaluation can tell a model that cannot copy lines from one that cannot fix."""
import pytest

from devcompanion.fix.patch import PatchError, apply, parse, propose

CODE = 'def fields(line: str) -> list[str]:\n    return line.split(3)\n'


def block(search: str, replace: str | None) -> str:
    body = "" if replace is None else replace + "\n"
    return f"<<<<<<< SEARCH\n{search}\n=======\n{body}>>>>>>> REPLACE"


def test_an_exact_block_applies():
    done = apply(CODE, parse(block("    return line.split(3)", '    return line.split(",")')))
    assert done.text == 'def fields(line: str) -> list[str]:\n    return line.split(",")\n'
    assert not done.loose
    assert done.added == ['    return line.split(",")']


def test_prose_and_fences_around_a_block_are_ignored():
    reply = "Here is the fix:\n```\n" + block("    return line.split(3)", "    return line.split()") + "\n```\n"
    done = propose(CODE, reply)
    assert done.form == "blocks"
    assert done.text.endswith("    return line.split()\n")


def test_a_block_copied_without_indentation_is_shifted_into_place_and_marked_loose():
    # Seen from qwen2.5-coder:3b: the right fix, with its indentation stripped. Taken literally
    # it moves the `return` out of the function.
    code = "def version(match):\n    return match.group(1)\n"
    done = apply(code, parse(block("return match.group(1)", "if match:\n    return match.group(1)\nreturn ''")))
    assert done.loose
    assert done.text == "def version(match):\n    if match:\n        return match.group(1)\n    return ''\n"


def test_inconsistent_indentation_is_applied_as_written():
    code = "def f():\n    x = 1\n    return x\n"
    done = apply(code, parse(block("  x = 1\nreturn x", "  x = 2\nreturn x")))
    assert done.loose
    assert done.text == "def f():\n  x = 2\nreturn x\n"


def test_a_search_that_is_not_in_the_code_is_refused():
    with pytest.raises(PatchError) as error:
        apply(CODE, parse(block("    return text.split(3)", "    return text.split()")))
    assert error.value.reason == "not_found"


def test_a_search_that_matches_twice_is_refused():
    code = "x = 1\ny = 2\nx = 1\n"
    with pytest.raises(PatchError) as error:
        apply(code, parse(block("x = 1", "x = 3")))
    assert error.value.reason == "ambiguous"


def test_a_reply_with_neither_blocks_nor_code_is_refused():
    with pytest.raises(PatchError) as error:
        propose(CODE, "Use a string separator instead of an int.")
    assert error.value.reason == "no_blocks"


def test_blocks_apply_in_order_and_an_empty_replacement_deletes():
    code = "import os\nimport sys\n\nprint(sys.argv)\n"
    done = apply(code, parse(block("import os", None) + "\n" + block("print(sys.argv)", "print(sys.argv[1:])")))
    assert done.text == "import sys\n\nprint(sys.argv[1:])\n"


def test_lines_the_replacement_keeps_do_not_count_as_added():
    code = "def f(x: int) -> int:\n    return x\n"
    done = apply(code, parse(block("def f(x: int) -> int:\n    return x", "def f(x: int) -> int:\n    return x + 1")))
    assert done.added == ["    return x + 1"]


def test_reasoning_before_the_end_of_thinking_is_not_the_answer():
    # A thinking model drafts code while it reasons; only what follows </think> is its answer.
    draft = "```python\ndef fields(line: str) -> list[str]:\n    return line.split(4)\n```"
    answer = block("    return line.split(3)", '    return line.split(",")')
    assert "split(\",\")" in propose(CODE, f"Let me think.\n{draft}\n</think>\n{answer}").text
    with pytest.raises(PatchError):
        propose(CODE, f"Let me think.\n{draft}\n</think>\nSEARCH\n    return line.split(3)\nREPLACE")


def test_a_fenced_rewrite_of_the_whole_module_replaces_it():
    code = 'import re\n\n\ndef fields(line: str) -> list[str]:\n    return line.split(3)\n'
    reply = 'Fixed:\n```python\nimport re\n\n\ndef fields(line: str) -> list[str]:\n    return line.split(",")\n```'
    done = propose(code, reply)
    assert done.form == "rewrite"
    assert done.text == 'import re\n\n\ndef fields(line: str) -> list[str]:\n    return line.split(",")\n'


def test_a_whole_module_rewrite_replaces_the_broken_statement_too():
    # The broken line is not in the reply, so it cannot be matched by its text; the rewrite still
    # has every unit the file has.
    code = "from math hypot\n\n\ndef distance(x: float, y: float) -> float:\n    return hypot(x, y)\n"
    reply = "```python\nfrom math import hypot\n\n\ndef distance(x: float, y: float) -> float:\n    return hypot(x, y)\n```"
    assert propose(code, reply).text == code.replace("from math hypot", "from math import hypot")


def test_a_rewrite_of_one_definition_replaces_only_it_and_merges_its_imports():
    # qwen3-coder:30b's habit: the corrected function alone, in a fence.
    code = ('from datetime import date\n\nWEEK = 7\n\n\n'
            'def next_review(last: date) -> date:\n    return last + timedelta(days="7")\n\n\n'
            'def other() -> int:\n    return WEEK\n')
    reply = ('```python\nfrom datetime import timedelta\n\n'
             'def next_review(last: date) -> date:\n    return last + timedelta(days=WEEK)\n```')
    assert propose(code, reply).text == (
        'from datetime import date, timedelta\n\nWEEK = 7\n\n\n'
        'def next_review(last: date) -> date:\n    return last + timedelta(days=WEEK)\n\n\n'
        'def other() -> int:\n    return WEEK\n')


def test_decorators_and_closing_brackets_stay_with_their_unit():
    code = ('@dataclass\nclass User:\n    name: str\n\n\nLEVELS = {\n    "low": 1\n    "high": 2,\n}\n\n\n'
            'def level(name: str) -> int:\n    return LEVELS[name]\n')
    reply = ('```python\nLEVELS = {\n    "low": 1,\n    "high": 2,\n}\n\n\n'
             'def level(name: str) -> int:\n    return LEVELS[name]\n```')
    assert propose(code, reply).text == code.replace('"low": 1\n', '"low": 1,\n')


def test_a_rewrite_that_names_nothing_in_the_file_is_refused():
    with pytest.raises(PatchError) as error:
        propose(CODE, "```python\ndef other() -> None:\n    pass\n```")
    assert error.value.reason == "not_found"
