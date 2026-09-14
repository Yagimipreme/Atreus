"""Machine messages -> human problems: the interpretation layer over the language server.

Written against the screenshot that motivated it: four basedpyright errors in a ten-line file,
two of them about `test_string.split(3)` and two about one unfinished `from` import.
"""
from devcompanion.present import findings as findings_out
from devcompanion.present.problems import normalise, simplify_type

MANIFEST = {"test.py": {"sha": "abc", "origin": "disk"}}


def diag(line, col, message, code=None, end_col=None, source="basedpyright"):
    return {"line": line, "col": col, "end_line": line, "end_col": end_col or col + 1,
            "severity": "error", "message": message, "code": code, "source": source}


SPLIT = [
    diag(8, 5, 'No overloads for "split" match the provided arguments\n  Argument types: (Literal[3])',
         "reportCallIssue", 25),
    diag(8, 23, 'Argument of type "Literal[3]" cannot be assigned to parameter "sep" of type '
                '"str | None" in function "split"\n  Type "Literal[3]" is not assignable to type '
                '"str | None"', "reportArgumentType", 24),
]
IMPORT = [diag(10, 10, "Expected module name"), diag(10, 10, 'Expected "import"')]


def publish(items):
    return findings_out.from_diagnostics({"test.py": items}, MANIFEST)


def test_one_mistake_reported_twice_is_one_problem():
    (f,) = publish(SPLIT)
    assert f["title"] == "split() expects str | None, got int"
    assert f["facts"] == {"symbol": "split()", "parameter": "sep", "expected": "str | None", "got": "int"}
    assert f["diagnostics"] == 2 and [e["ref"] for e in f["evidence"]] == ["reportArgumentType", "reportCallIssue"]
    assert f["location"]["col"] == 23, "the caret belongs under the argument, not the call"


def test_two_syntax_errors_in_one_import_are_one_problem():
    (f,) = publish(IMPORT)
    assert f["title"] == "incomplete import statement"
    assert f["diagnostics"] == 2


def test_four_diagnostics_are_two_problems():
    assert [f["title"] for f in publish(SPLIT + IMPORT)] == [
        "split() expects str | None, got int", "incomplete import statement"]


def test_unrelated_errors_on_one_line_stay_apart():
    items = [diag(3, 1, '"foo" is not defined', "reportUndefinedVariable", 4),
             diag(3, 10, '"bar" is not defined', "reportUndefinedVariable", 13)]
    assert [f["title"] for f in publish(items)] == ["foo is not defined", "bar is not defined"]


def test_an_unrecognised_message_keeps_its_first_line():
    reading = normalise("something no rule knows\n  and the explanation under it")
    assert reading.sentence == "something no rule knows" and reading.facts == {}


def test_literal_types_read_as_the_type_that_was_written():
    assert simplify_type("Literal[3]") == "int"
    assert simplify_type('Literal["a", "b"]') == "str"
    assert simplify_type("Literal[True]") == "bool"
    assert simplify_type("Literal[b'x']") == "bytes"
    assert simplify_type("list[int]") == "list[int]"


def test_every_fact_appears_in_its_sentence():
    """The editor colours a fact by finding it in the sentence; a fact the sentence does not
    contain would silently lose its colour, which is exactly the mismatch it was meant to show."""
    messages = [SPLIT[0]["message"], SPLIT[1]["message"], '"foo" is not defined',
                'Cannot access attribute "x" for class "Literal[1]"',
                'Import "numpy" could not be resolved',
                'Type "Literal[1]" is not assignable to declared type "str"',
                'Argument missing for parameter "carry"', 'No parameter named "carry"']
    for message in messages:
        reading = normalise(message)
        assert reading.facts, message
        for key in ("symbol", "expected", "got"):
            if key in reading.facts:
                assert reading.facts[key] in reading.sentence, (message, key)
