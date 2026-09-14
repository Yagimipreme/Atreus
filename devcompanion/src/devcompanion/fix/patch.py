"""A model reply -> an edited text, or the reason there is none.

Two answer forms are accepted, because models use both whatever they are asked for:

  blocks   SEARCH/REPLACE blocks (aider's format), line-based rather than a unified diff because
           small models count lines badly and copy them well. A block's search lines must occur
           exactly once. When they occur once only ignoring indentation, the replacement is
           shifted by the indentation the matched lines have, and the edit is marked `loose`.
  rewrite  no blocks, but a fenced code block holding the corrected module or the corrected
           definitions -- how qwen3-coder:30b answers at temperature 0 though asked for blocks.
           A rewrite that names every definition of the file and has at least as many top-level
           units replaces the file; otherwise each named unit (definition or assignment)
           replaces the unit of that name, and `from` imports it adds are merged into the file's.

A thinking model's reasoning before `</think>` is not its answer and is ignored. Neither form is
trusted: the checker decides whether the result is right.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

BLOCK = re.compile(r"^<{5,} *SEARCH *\n(.*?)^={5,} *\n(.*?)^>{5,} *REPLACE *$", re.M | re.S)
FENCE = re.compile(r"^```[\w+-]*[ \t]*\n(.*?)^```[ \t]*$", re.M | re.S)
NAME = re.compile(r"(?:async\s+def|def|class)\s+(\w+)|(\w+)\s*(?::[^=]+)?=(?!=)")
CONTINUATION = re.compile(r"[)\]}]|(?:elif|else|except|finally)\b")
IMPORT = re.compile(r"(?:import\s|from\s+\S+\s+import\s)")
FROM_IMPORT = re.compile(r"from\s+(\S+)\s+import\s+([\w\s,]+?)\s*$")


class PatchError(Exception):
    """Why a reply is not an edit: `no_blocks`, `empty_search`, `not_found` or `ambiguous`."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


@dataclass
class Block:
    search: list[str]
    replace: list[str]


@dataclass
class Applied:
    text: str
    form: str = "blocks"
    loose: bool = False
    added: list[str] = field(default_factory=list)   # lines that were not already there


def _lines(body: str) -> list[str]:
    return body[:-1].split("\n") if body else []


def parse(reply: str) -> list[Block]:
    blocks = [Block(_lines(m.group(1)), _lines(m.group(2)))
              for m in BLOCK.finditer(reply.replace("\r\n", "\n"))]
    if not blocks:
        raise PatchError("no_blocks")
    return blocks


def _find(lines: list[str], needle: list[str], same: Callable[[str, str], bool]) -> list[int]:
    return [i for i in range(len(lines) - len(needle) + 1)
            if all(same(lines[i + j], needle[j]) for j in range(len(needle)))]


def _indent(line: str) -> str:
    return line[:len(line) - len(line.lstrip())]


def _reindent(replace: list[str], search: list[str], found: list[str]) -> list[str]:
    """A block copied with its indentation stripped keeps its shape: shift the replacement by what
    the matched lines have in front of the search lines. Only one consistent extra prefix is
    added; any other drift is left as it is, for the checker to refuse."""
    shifts = set()
    for s, f in zip(search, found):
        if s.strip():
            have, want = _indent(s), _indent(f)
            shifts.add(want[:len(want) - len(have)] if want.endswith(have) else None)
    if len(shifts) != 1 or None in shifts:
        return replace
    shift = shifts.pop()
    return [shift + line if line.strip() else line for line in replace]


def apply(text: str, blocks: list[Block]) -> Applied:
    lines = text.split("\n")
    result = Applied(text)
    for block in blocks:
        if not block.search:
            raise PatchError("empty_search")
        replace = block.replace
        at = _find(lines, block.search, lambda a, b: a.rstrip() == b.rstrip())
        if not at:
            at = _find(lines, block.search, lambda a, b: a.strip() == b.strip())
            if len(at) == 1:
                result.loose = True
                replace = _reindent(block.replace, block.search, lines[at[0]:at[0] + len(block.search)])
        if not at:
            raise PatchError("not_found", block.search[0].strip())
        if len(at) > 1:
            raise PatchError("ambiguous", block.search[0].strip())
        start = at[0]
        lines[start:start + len(block.search)] = replace
        kept = {line.strip() for line in block.search}
        result.added += [line for line in replace if line.strip() not in kept]
    result.text = "\n".join(lines)
    return result


def _name(line: str) -> str | None:
    match = NAME.match(line)
    return (match.group(1) or match.group(2)) if match else None


def _units(lines: list[str]) -> list[list]:
    """Top-level units of a module as [name, start, end): a definition with its decorators and
    body, an assignment, or any other statement (name None). Closing brackets and
    elif/else/except/finally at column 0 continue the unit before them; trailing blank lines are
    spacing, not part of a unit."""
    units: list[list] = []
    for i, line in enumerate(lines):
        if not line.strip() or line[0].isspace() or line.startswith("#") or CONTINUATION.match(line):
            continue
        last = units[-1] if units else None
        if last is not None and lines[last[1]].startswith("@") and all(
                not l.strip() or l.startswith("@") for l in lines[last[1]:i]):
            last[0] = last[0] or _name(line)
            continue
        if last is not None:
            last[2] = i
        units.append([_name(line), i, len(lines)])
    for unit in units:
        while unit[2] > unit[1] + 1 and not lines[unit[2] - 1].strip():
            unit[2] -= 1
    return units


def _add_import(lines: list[str], line: str) -> None:
    """`from m import b` joins an existing `from m import a` as `from m import a, b`; anything else
    goes after the file's last top-level import."""
    new = FROM_IMPORT.match(line)
    if new:
        for i, old in enumerate(lines):
            have = FROM_IMPORT.match(old)
            if have and have.group(1) == new.group(1):
                names = [n.strip() for n in have.group(2).split(",")]
                names += [n.strip() for n in new.group(2).split(",") if n.strip() not in names]
                lines[i] = f"from {new.group(1)} import {', '.join(names)}"
                return
    at = max((i + 1 for i, old in enumerate(lines) if IMPORT.match(old)), default=0)
    lines[at:at] = [line]


def rewrite(text: str, reply: str) -> Applied:
    fences = FENCE.findall(reply.replace("\r\n", "\n"))
    if not fences:
        raise PatchError("no_blocks")
    code = fences[-1].rstrip("\n")
    new, lines = code.split("\n"), text.split("\n")
    known = {line.strip() for line in lines}
    added = [line for line in new if line.strip() and line.strip() not in known]
    ours, theirs = _units(lines), _units(new)
    given = {u[0]: u for u in theirs if u[0]}
    present = {line.strip() for line in new}
    if ours and all(u[0] in given for u in ours if u[0]) and (
            len(theirs) >= len(ours) or all(lines[u[1]].strip() in present for u in ours if not u[0])):
        return Applied(code + "\n", form="rewrite", added=added)
    if not given:
        raise PatchError("not_found", "no definition in the rewrite")
    replacements = []
    for name, (_, start, end) in given.items():
        same = [u for u in ours if u[0] == name]
        if len(same) != 1:
            raise PatchError("not_found" if not same else "ambiguous", name)
        replacements.append((same[0][1], same[0][2], new[start:end]))
    result = list(lines)
    for start, end, body in sorted(replacements, key=lambda r: r[0], reverse=True):
        result[start:end] = body
    for line in new:
        if IMPORT.match(line) and line.strip() not in known:
            _add_import(result, line)
    return Applied("\n".join(result), form="rewrite", added=added)


def propose(text: str, reply: str) -> Applied:
    """SEARCH/REPLACE blocks when the answer has any, otherwise a fenced rewrite."""
    answer = reply.rpartition("</think>")[2]
    try:
        blocks = parse(answer)
    except PatchError:
        return rewrite(text, answer)
    return apply(text, blocks)
