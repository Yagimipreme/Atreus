"""Machine messages -> human problems: the interpretation layer over the language server.

Written against the screenshots that motivated it: four basedpyright errors in a ten-line file,
two of them about `test_string.split(3)` and two about one unfinished `from` import; and a
None operand still worded as `Operator "+" not supported for types "None" and "Literal[1]"`.
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
    assert (f["location"]["col"], f["location"]["end_col"]) == (23, 24), \
        "the caret and the code highlight belong on the argument, not the call"


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


def test_a_none_operand_is_said_as_a_possible_none():
    reading = normalise('Operator "+" not supported for types "None" and "Literal[1]"\n'
                        '  Operator "+" not supported for types "None" and "Literal[1]"')
    assert reading.sentence == "possible None used with +"
    assert reading.facts == {"found": "None", "operator": "+", "with": "int"}
    assert normalise('Operator "+" not supported for "None"').sentence == "possible None used with +"


def test_an_operator_without_none_names_both_sides():
    reading = normalise('Operator "+" not supported for types "Literal[\'a\']" and "Literal[1]"')
    assert reading.sentence == "+ not supported between str and int"
    assert reading.facts == {"operator": "+", "left": "str", "right": "int"}


def test_an_optional_argument_is_found_against_required():
    reading = normalise('Argument of type "User | None" cannot be assigned to parameter "user" of '
                        'type "User" in function "authenticate"')
    assert reading.sentence == "possible None passed to authenticate()"
    assert reading.facts == {"symbol": "authenticate()", "found": "User | None",
                             "required": "User", "parameter": "user"}


def test_a_return_type_mismatch_says_returned_and_expected():
    reading = normalise('Type "Literal[\'yes\']" is not assignable to return type "bool"')
    assert reading.sentence == "returns str, expected bool"
    assert reading.facts == {"returned": "str", "expected": "bool"}


def test_an_attribute_of_possible_none():
    reading = normalise('"name" is not a known attribute of "None"')
    assert reading.sentence == "name accessed on possible None"
    assert reading.facts == {"symbol": "name", "found": "None"}


def test_an_unrecognised_message_keeps_its_first_line():
    reading = normalise("something no rule knows\n  and the explanation under it")
    assert reading.sentence == "something no rule knows" and reading.facts == {}


def test_literal_types_read_as_the_type_that_was_written():
    assert simplify_type("Literal[3]") == "int"
    assert simplify_type('Literal["a", "b"]') == "str"
    assert simplify_type("Literal[True]") == "bool"
    assert simplify_type("Literal[b'x']") == "bytes"
    assert simplify_type("list[int]") == "list[int]"


def test_every_highlighted_fact_appears_in_its_sentence():
    """The editor colours these facts by finding them in the sentence; one the sentence does not
    contain would silently lose its colour, which is exactly the mismatch it was meant to show.
    `found`, `required` and the where-facts are shown in the block under an opened problem and
    need not appear in the sentence."""
    messages = [SPLIT[0]["message"], SPLIT[1]["message"], '"foo" is not defined',
                'Cannot access attribute "x" for class "Literal[1]"',
                'Import "numpy" could not be resolved',
                'Type "Literal[1]" is not assignable to declared type "str"',
                'Type "Literal[1]" is not assignable to return type "str"',
                'Argument missing for parameter "carry"', 'No parameter named "carry"',
                'Operator "+" not supported for types "None" and "Literal[1]"',
                '"name" is not a known attribute of "None"',
                '"sep" is not a known attribute of module "os"']
    for message in messages:
        reading = normalise(message)
        assert reading.facts, message
        for key in ("symbol", "expected", "got", "returned", "missing"):
            if key in reading.facts:
                assert reading.facts[key] in reading.sentence, (message, key)
