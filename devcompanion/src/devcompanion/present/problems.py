"""Raw diagnostics -> problems: what the language server said, as a developer would say it.

A language server reports machine messages, and one mistake routinely produces several:
`test_string.split(3)` is both "No overloads for split" and "Argument of type Literal[3] cannot
be assigned to parameter sep". Echoing both is two rows for one problem, each worded for a type
checker. This module does the two things that make the panel an interpretation rather than a
second copy of the sign column:

  normalise  one message -> one short sentence, plus the facts it names, so the editor can show
             what the code has against what it needs instead of colouring a whole line red
  group      messages about the same mistake -> one problem, keeping every raw message as
             evidence, so nothing is lost and all of it is one keypress away

Facts use one small vocabulary, so a developer learns to read the block under an opened problem
at a glance. What the code has: `got`, `found`, `returned`, `missing`. What it needs:
`expected`, `required`. Where: `parameter`, `operator`, `with`, `left`, `right`, `module`. And
`symbol`, the name the sentence is about.

Deterministic and table-driven. A message no rule recognises keeps its own first line. A model
may later rewrite sentences; it would not replace this, because the grouping and the facts are
what make a model's sentence checkable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Reading:
    sentence: str
    facts: dict[str, str] = field(default_factory=dict)
    specificity: int = 0          # how much the message says about the mistake; wins the headline
    topic: str | None = None      # the construct it is about, when several messages share one


def flat(text: object) -> str:
    return " ".join(str(text or "").split())


def first_line(text: object) -> str:
    for raw in str(text or "").splitlines():
        if raw.strip():
            return flat(raw)
    return ""


def simplify_type(t: str) -> str:
    """`Literal[3]` is what the checker inferred; `int` is what the developer wrote."""
    m = re.fullmatch(r"Literal\[(.+)\]", t.strip())
    if not m:
        return t
    value = m.group(1).split(",")[0].strip()
    if value in ("True", "False"):
        return "bool"
    if value[:2] in ('b"', "b'"):
        return "bytes"
    if value[:1] in ("'", '"'):
        return "str"
    if re.fullmatch(r"-?\d+", value):
        return "int"
    if re.fullmatch(r"-?\d*\.\d+", value):
        return "float"
    return t


def may_be_none(t: str) -> bool:
    return bool(re.search(r"(^|\|)\s*None\s*(\||$)", t)) or t.startswith("Optional[")


def _argument(m: re.Match) -> Reading:
    got, parameter, expected, function = simplify_type(m[1]), m[2], m[3], m[4]
    if may_be_none(got) and not may_be_none(expected):
        return Reading(f"possible None passed to {function}()",
                       {"symbol": f"{function}()", "found": got, "required": expected,
                        "parameter": parameter}, specificity=3)
    return Reading(f"{function}() expects {expected}, got {got}",
                   {"symbol": f"{function}()", "got": got, "expected": expected,
                    "parameter": parameter}, specificity=3)


def _operator(m: re.Match) -> Reading:
    op, left, right = m[1], simplify_type(m[2]), simplify_type(m[3])
    for side, other in ((left, right), (right, left)):
        if may_be_none(side):
            return Reading(f"possible None used with {op}",
                           {"found": side, "operator": op, "with": other}, specificity=3)
    return Reading(f"{op} not supported between {left} and {right}",
                   {"operator": op, "left": left, "right": right}, specificity=3)


def _assignment(m: re.Match) -> Reading:
    got = simplify_type(m[1])
    return Reading(f"expected {m[2]}, got {got}", {"got": got, "expected": m[2]}, specificity=2)


def _returned(m: re.Match) -> Reading:
    got = simplify_type(m[1])
    return Reading(f"returns {got}, expected {m[2]}", {"returned": got, "expected": m[2]},
                   specificity=2)


def _attribute(m: re.Match) -> Reading:
    owner = simplify_type(m[2])
    if may_be_none(owner):
        return Reading(f"{m[1]} accessed on possible None", {"symbol": m[1], "found": owner}, 3)
    return Reading(f"{owner} has no attribute {m[1]}", {"symbol": m[1], "got": owner}, specificity=2)


def _none(action: str) -> object:
    return lambda m: Reading(f"possible None {action}", {"found": "None"}, specificity=3)


# Searched in order over the whole flattened message, so a specific rule wins over a general one
# even when the specific wording is on a later line. Written against basedpyright and pyright.
RULES: list[tuple[re.Pattern, object]] = [(re.compile(p), build) for p, build in [
    (r'Argument of type "(.+?)" cannot be assigned to parameter "(\w+)" of type "(.+?)" '
     r'in function "(\w+)"', _argument),
    (r'Operator "(.+?)" not supported for types "(.+?)" and "(.+?)"', _operator),
    (r'Operator "(.+?)" not supported for "None"',
     lambda m: Reading(f"possible None used with {m[1]}", {"found": "None", "operator": m[1]}, 3)),
    (r'Type "(.+?)" is not assignable to return type "(.+?)"', _returned),
    (r'Type "(.+?)" is not assignable to declared type "(.+?)"', _assignment),
    (r'"(\w+)" is not a known attribute of module "(.+?)"',
     lambda m: Reading(f"{m[2]} has no attribute {m[1]}", {"symbol": m[1], "module": m[2]}, 2)),
    (r'"(\w+)" is not a known attribute of "(None)"', _attribute),
    (r'Cannot access attribute "(\w+)" for class "(.+?)"', _attribute),
    (r'Object of type "None" is not subscriptable', _none("subscripted")),
    (r'Object of type "None" cannot be called', _none("called")),
    (r'Object of type "None" cannot be used as iterable value', _none("iterated")),
    (r'No overloads for "(\w+)" match the provided arguments',
     lambda m: Reading(f"{m[1]}() has no overload for these arguments", {"symbol": f"{m[1]}()"}, 1)),
    (r'Argument missing for parameter "(\w+)"',
     lambda m: Reading(f"missing argument {m[1]}", {"missing": m[1]}, 2)),
    (r'Arguments missing for parameters (.+)',
     lambda m: Reading(f"missing arguments {m[1].replace(chr(34), '')}",
                       {"missing": m[1].replace(chr(34), "")}, 2)),
    (r'Expected (\d+) positional arguments?',
     lambda m: Reading(f"too many positional arguments, expects {m[1]}", {"expected": m[1]}, 2)),
    (r'No parameter named "(\w+)"',
     lambda m: Reading(f"no parameter named {m[1]}", {"got": m[1]}, 2)),
    (r'"(\w+)" is not defined',
     lambda m: Reading(f"{m[1]} is not defined", {"symbol": m[1]}, 2)),
    (r'"(\w+)" is possibly unbound',
     lambda m: Reading(f"{m[1]} may be unbound here", {"symbol": m[1]}, 2)),
    (r'Import "(.+?)" could not be resolved',
     lambda m: Reading(f"cannot import {m[1]}", {"missing": m[1]}, 2)),
    (r'Expected module name',
     lambda m: Reading("import is missing its module name", {}, 1, topic="import")),
    (r'Expected "import"',
     lambda m: Reading('from-import is missing "import"', {}, 1, topic="import")),
]]


def normalise(message: object) -> Reading:
    text = flat(message)
    for pattern, build in RULES:
        m = pattern.search(text)
        if m:
            return build(m)
    return Reading(first_line(message))


@dataclass
class Problem:
    members: list[dict]           # raw diagnostics, most informative first
    readings: list[Reading]

    @property
    def lead(self) -> dict:
        return self.members[0]

    @property
    def sentence(self) -> str:
        topics = {r.topic for r in self.readings}
        if len(self.readings) > 1 and len(topics) == 1 and None not in topics:
            return f"incomplete {next(iter(topics))} statement"
        return self.readings[0].sentence

    @property
    def facts(self) -> dict[str, str]:
        return self.readings[0].facts


def _span(d: dict) -> tuple[tuple[int, int], tuple[int, int]]:
    start = (d.get("line") or 0, d.get("col") or 0)
    end = (d.get("end_line") or start[0], d.get("end_col") or start[1])
    return start, max(start, end)


def _related(a: tuple[dict, Reading], b: tuple[dict, Reading]) -> bool:
    """Two messages about one mistake: on one line, and overlapping, or naming the same symbol,
    or about the same construct, or both syntax errors from one source (no rule code)."""
    (da, ra), (db, rb) = a, b
    if (da.get("line") or 0) != (db.get("line") or 0):
        return False
    (sa, ea), (sb, eb) = _span(da), _span(db)
    if sa < eb and sb < ea:
        return True
    symbol = ra.facts.get("symbol")
    if symbol and symbol == rb.facts.get("symbol"):
        return True
    if ra.topic is not None and ra.topic == rb.topic:
        return True
    return not da.get("code") and not db.get("code") and da.get("source") == db.get("source")


def group(items: list[dict]) -> list[Problem]:
    read = [(d, normalise(d.get("message"))) for d in items]
    parent = list(range(len(read)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(read)):
        for j in range(i + 1, len(read)):
            if _related(read[i], read[j]):
                parent[root(i)] = root(j)
    groups: dict[int, list[tuple[dict, Reading]]] = {}
    for i, pair in enumerate(read):
        groups.setdefault(root(i), []).append(pair)
    out = []
    for pairs in groups.values():
        pairs.sort(key=lambda p: (-p[1].specificity, p[0].get("col") or 0))
        out.append(Problem([d for d, _ in pairs], [r for _, r in pairs]))
    out.sort(key=lambda p: (p.lead.get("line") or 0, p.lead.get("col") or 0))
    return out
