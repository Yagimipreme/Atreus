"""The context packet for a proposed fix: the problem as the panel says it, the checker's own
words, and the code around it -- nothing else. Small enough for a 4K local context with room left
to answer; a file longer than `whole` lines is cut to its imports and a window per problem.
"""
from __future__ import annotations

import re

from devcompanion.present.problems import Problem, first_line

SYSTEM = """You fix type-checker problems in Python code. Reply with SEARCH/REPLACE blocks and nothing else:

<<<<<<< SEARCH
lines copied exactly from the code
=======
the lines that replace them
>>>>>>> REPLACE

Copy SEARCH lines exactly, with their indentation, and enough of them to match one place.
Make the smallest change that fixes the problem the way the code's names, docstrings and callers
intend. Never silence the checker: no `# type: ignore`, no `cast`, no `Any`."""


def excerpt(lines: list[str], at: list[int], window: int = 12, whole: int = 80) -> list[str]:
    if len(lines) <= whole:
        return lines
    keep: set[int] = set()
    head = next((i for i, line in enumerate(lines) if re.match(r"(async def|def|class|@)", line)), 0)
    keep.update(range(min(head, 20)))
    for line in at:
        keep.update(range(max(0, line - 1 - window), min(len(lines), line + window)))
    out, previous = [], -1
    for i in sorted(keep):
        if i != previous + 1:
            out.append("# ...")
        out.append(lines[i])
        previous = i
    if previous != len(lines) - 1:
        out.append("# ...")
    return out


def build(path: str, text: str, problems: list[Problem]) -> str:
    lines = text.splitlines()
    out = [f"File: {path}", ""]
    for n, problem in enumerate(problems, 1):
        line = problem.lead.get("line") or 1
        out.append(f"Problem {n}: {problem.sentence}")
        if problem.facts:
            out.append("  " + " · ".join(f"{k} {v}" for k, v in problem.facts.items()))
        if 0 < line <= len(lines):
            out.append(f"  at line {line}: {lines[line - 1].strip()}")
        for d in problem.members:
            code = f" [{d['code']}]" if d.get("code") else ""
            out.append(f"  checker: {first_line(d.get('message'))}{code}")
        out.append("")
    out += ["Code:", "```python", *excerpt(lines, [p.lead.get("line") or 1 for p in problems]), "```"]
    return "\n".join(out)
