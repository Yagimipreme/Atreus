"""Checked fixes for the problems in one saved file.

For each problem, in line order and at most `limit` per revision: build the packet (prompt.py),
ask the `passive.fix` routing chain (config.py, llm/route.py), and let the gate (check.py) decide.
A proposal the gate calls `checked` comes back as line edits and a diff, with any warning it
introduced; anything else comes back with its reason, so the evidence says why no fix is offered.

What the gate sees depends on the `project`:
- **Given one** (the engine always gives one): the file is checked inside a shadow tree of the whole
  workspace, with its unsaved buffers (fix/project.py). Its imports resolve, and a problem that
  exists only through another module can be fixed and checked.
- **Without one:** the file is checked alone.

Either way, a problem the checker does not report is `not_visible` and is never sent to a model: a
fix nothing can check is not offered.

**One fix can resolve several problems.** The model routinely rewrites the file and fixes more than
it was asked about.
- **Before asking about a problem**, every fix already checked for this revision is tried against
  that problem's targets. If one removes them too, it is that problem's fix as well, and the model is
  not asked.
- **Every problem resolved by the same edits** carries the same `fix_id`, with their lines in
  `covers`, so the panel offers the fix once.
"""
from __future__ import annotations

import difflib
import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Callable

from devcompanion.config import Config
from devcompanion.fix import check, prompt
from devcompanion.fix.project import Project
from devcompanion.llm import providers, route
from devcompanion.present.problems import Problem, flat

LIMIT = 3
TOKENS = 300


@dataclass
class Proposal:
    problem: str                       # Problem.key
    line: int
    col: int
    outcome: str                       # checked | refused | not_visible | no_route | a reply status
    detail: str = ""
    profile: str | None = None
    edits: list[dict] = field(default_factory=list)   # {line, end_line, text}: 1-based, end exclusive
    diff: str = ""
    warnings: list[str] = field(default_factory=list)
    covers: list[int] = field(default_factory=list)   # lines of every problem these same edits resolve
    fix_id: str = ""                                   # shared by every problem these same edits resolve

    @property
    def transient(self) -> bool:
        """No model answered, which says nothing about the problem: not worth recording, so the
        next revision asks again."""
        return self.outcome not in ("checked", "refused", "not_visible")


def targets(problem: Problem, before: list[dict]) -> list[dict]:
    """The copy's diagnostics that are this problem: the same rule on the same line."""
    wanted = {(d.get("code") or "", d.get("line")) for d in problem.members}
    return [d for d in before if (d.get("code") or "", d.get("line")) in wanted]


def edits(before: str, after: str) -> list[dict]:
    """Line-range replacements that turn `before` into `after`, for the adapter to apply to a buffer."""
    a, b = before.splitlines(keepends=True), after.splitlines(keepends=True)
    return [{"line": i1 + 1, "end_line": i2 + 1, "text": "".join(b[j1:j2])}
            for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes()
            if tag != "equal"]


def propose(config: Config, path: str, text: str, problems: list[Problem], ask=providers.ask,
            binary: str | None = None, limit: int = LIMIT,
            stale: Callable[[], bool] = lambda: False, project: Project | None = None) -> list[Proposal]:
    """Raises check.CheckerUnavailable when there is no checker: without one nothing can be vouched for."""
    before = check.diagnose({path: text}, binary, project=project)[path]
    unseen = ("the checker does not report it for this revision" if project is not None
              else "the checker, seeing this file alone, does not report it")
    out: list[Proposal] = []
    vouched: list[tuple[Proposal, check.Verdict]] = []
    for problem in problems[:limit]:
        if stale():
            break
        lead = problem.lead
        base = {"problem": problem.key, "line": lead.get("line") or 1, "col": lead.get("col") or 1}
        wanted = targets(problem, before)
        if not wanted:
            out.append(Proposal(**base, outcome="not_visible", detail=unseen))
            continue
        covering = next((p for p, v in vouched if not check.remaining(wanted, before, v.after)), None)
        if covering is not None:
            out.append(replace(covering, **base))
            continue
        judged: list[check.Verdict] = []

        def gate(reply: str, wanted: list[dict] = wanted) -> bool:
            verdict = check.judge(path, text, reply, wanted, before, binary, project=project)
            judged.append(verdict)
            return verdict.checked

        answer = route.run(config, "passive.fix", prompt.SYSTEM, prompt.build(path, text, [problem]),
                           TOKENS, gate=gate, ask=ask)
        if answer.ok:
            accepted = judged[-1]
            diff = "".join(difflib.unified_diff(text.splitlines(keepends=True),
                                                accepted.text.splitlines(keepends=True), f"a/{path}", f"b/{path}"))
            proposal = Proposal(**base, outcome="checked", profile=answer.profile, edits=edits(text, accepted.text),
                                diff=diff, warnings=[flat(d["message"]) for d in accepted.warnings])
            vouched.append((proposal, accepted))
            out.append(proposal)
        elif answer.unavailable:
            out.append(Proposal(**base, outcome="no_route", detail=answer.unavailable))
        elif judged:
            last = judged[-1]
            out.append(Proposal(**base, outcome="refused", detail=f"{last.outcome}: {last.detail}".rstrip(": "),
                                profile=answer.attempts[-1].profile))
        else:
            attempt = answer.attempts[-1] if answer.attempts else None
            out.append(Proposal(**base, outcome=attempt.outcome if attempt else "no_answer",
                                profile=attempt.profile if attempt else None))
    same_edits: dict[str, list[Proposal]] = {}
    for p in out:
        if p.outcome == "checked":
            same_edits.setdefault(json.dumps(p.edits, sort_keys=True), []).append(p)
    for key, group in same_edits.items():
        fix_id = hashlib.sha1(f"{path}\0{text}\0{key}".encode()).hexdigest()[:10]
        for p in group:
            p.fix_id, p.covers = fix_id, sorted({q.line for q in group})
    return out
