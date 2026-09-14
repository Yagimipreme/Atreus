"""Is a proposed fix mechanically sound? Cheapest tier first; the first failure is the outcome.

  no_patch         the reply did not apply to the exact text it was proposed against
  unparsable       the result is not Python
  suppressed       it silences the checker instead of fixing (`# type: ignore`, `cast`, `Any`)
  unresolved       a diagnostic it was asked to remove is still there
  new_diagnostics  it introduced an error that was not there before
  checked          none of the above; any warning it introduced is carried in `warnings`, and the
                   panel notes it next to the ✓ (`✓ fix checked · 1 new warning`)

A new warning notes rather than refuses because the gate compares against the broken code, so a
correct fix can carry a warning the broken code never reached (docs/evaluations/function-routing.md).

`checked` says the code is now consistent, not that it does what the developer meant:
`split(3)` -> `split("3")` is checked. Intent needs tests, and is reported apart from this.

Diagnostics are compared as a multiset of (rule, message), ignoring position, so an edit that
shifts lines does not make every later diagnostic look new.

The checker always runs in a scratch directory, and the developer's working tree is never written.
- **With a `project`:** the scratch directory is a shadow tree of the whole workspace, with unsaved
  buffers in place (fix/project.py). Imports, the project's configuration and its virtualenv then
  resolve as in the editor.
- **Without one:** the file is checked alone, and anything it imports is unknown.
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from devcompanion.fix import patch
from devcompanion.fix.project import Project, materialise
from devcompanion.present.problems import flat

# Mason is where a Neovim user's basedpyright usually lives, and it is not on PATH.
MASON = Path.home() / ".local/share/nvim/mason/bin/basedpyright"
SEVERITY = {"error": "error", "warning": "warn"}
SUPPRESSION = re.compile(r"type:\s*ignore|pyright:\s*ignore|\bcast\(|\bAny\b|\bnoqa\b")


class CheckerUnavailable(RuntimeError):
    pass


def checker() -> str | None:
    found = os.environ.get("COMPANION_BASEDPYRIGHT") or shutil.which("basedpyright")
    if found:
        return found
    return str(MASON) if MASON.exists() else None


@contextmanager
def _alone(files: dict[str, str]) -> Iterator[Path]:
    """A scratch directory holding only `files`."""
    with tempfile.TemporaryDirectory(prefix="companion-check-") as tmp:
        root = Path(tmp).resolve()
        for rel, text in files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        yield root


def diagnose(files: dict[str, str], binary: str | None = None, timeout_s: float = 120,
             project: Project | None = None) -> dict[str, list[dict]]:
    """Errors and warnings for each of `files` (relative path -> text), from one checker run, in
    the contract's diagnostic shape (1-based lines and columns). With a `project`, the files are
    checked in place within it."""
    binary = binary or checker()
    if not binary:
        raise CheckerUnavailable("basedpyright not found")
    out: dict[str, list[dict]] = {rel: [] for rel in files}
    scratch = materialise(project, files) if project is not None else _alone(files)
    with scratch as root:
        extra = ["--pythonpath", project.python] if project is not None and project.python else []
        proc = subprocess.run([binary, "--outputjson", *extra, *files], cwd=root,
                              capture_output=True, text=True, timeout=timeout_s)
        try:
            report = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise CheckerUnavailable(f"basedpyright gave no report: {proc.stderr.strip()[:200]}")
        for d in report.get("generalDiagnostics", []):
            severity = SEVERITY.get(d.get("severity"))
            try:
                rel = str(Path(d["file"]).resolve().relative_to(root))
            except ValueError:
                continue                   # a file reached through a link: not one that was asked about
            if severity is None or rel not in out:
                continue
            start, end = d["range"]["start"], d["range"]["end"]
            out[rel].append({"code": d.get("rule"), "line": start["line"] + 1,
                             "col": start["character"] + 1, "end_line": end["line"] + 1,
                             "end_col": end["character"] + 1, "message": d.get("message", ""),
                             "severity": severity, "source": "basedpyright"})
    return out


def key(d: dict) -> tuple[str, str]:
    return d.get("code") or "", flat(d.get("message"))


def rule(d: dict) -> str:
    return d.get("code") or ""


def _minus(items: list[dict], remove: list[dict], by=key) -> list[dict]:
    budget = Counter(by(d) for d in remove)
    kept = []
    for d in items:
        if budget[by(d)] > 0:
            budget[by(d)] -= 1
        else:
            kept.append(d)
    return kept


def introduced(before: list[dict], after: list[dict]) -> list[dict]:
    """The diagnostics in `after` that `before` does not account for."""
    return _minus(after, before)


def remaining(targets: list[dict], before: list[dict], after: list[dict]) -> list[dict]:
    """The asked-for diagnostics still present after the edit. Matched by rule, not wording:
    `split(4)` in place of `split(3)` is the same mistake with a different literal, and a message
    key would count it as resolved plus one new diagnostic."""
    wanted = {rule(t) for t in targets}
    return [d for d in _minus(after, _minus(before, targets), by=rule) if rule(d) in wanted]


@dataclass
class Verdict:
    outcome: str
    detail: str = ""
    text: str | None = None        # the patched code, once it parses
    form: str = ""                 # blocks | rewrite, once a patch applied
    loose: bool = False
    remaining: list[dict] = field(default_factory=list)
    new: list[dict] = field(default_factory=list)       # errors it introduced: these refuse
    warnings: list[dict] = field(default_factory=list)  # warnings it introduced: these are noted
    after: list[dict] = field(default_factory=list)     # everything the checker reported after the edit
    seconds: float = 0.0

    @property
    def checked(self) -> bool:
        return self.outcome == "checked"


def judge(path: str, before: str, reply: str, targets: list[dict], before_diagnostics: list[dict],
          binary: str | None = None, project: Project | None = None) -> Verdict:
    started = time.monotonic()

    def verdict(outcome: str, **kw) -> Verdict:
        return Verdict(outcome, seconds=time.monotonic() - started, **kw)

    try:
        applied = patch.propose(before, reply)
    except patch.PatchError as error:
        return verdict("no_patch", detail=str(error))
    shape = {"form": applied.form, "loose": applied.loose}
    try:
        ast.parse(applied.text)
    except SyntaxError as error:
        return verdict("unparsable", detail=f"line {error.lineno}: {error.msg}", **shape)
    silenced = [line.strip() for line in applied.added if SUPPRESSION.search(line)]
    if silenced:
        return verdict("suppressed", detail=silenced[0], text=applied.text, **shape)
    after = diagnose({path: applied.text}, binary, project=project)[path]
    left = remaining(targets, before_diagnostics, after)
    added = introduced(before_diagnostics, after)
    errors = [d for d in added if d["severity"] == "error"]
    warnings = [d for d in added if d["severity"] != "error"]
    outcome = "unresolved" if left else "new_diagnostics" if errors else "checked"
    detail = first_message(left or errors)
    return verdict(outcome, detail=detail, text=applied.text, remaining=left, new=errors,
                   warnings=warnings, after=after, **shape)


def first_message(items: list[dict]) -> str:
    return flat(items[0]["message"])[:160] if items else ""
