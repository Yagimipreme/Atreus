"""Evidence records -> contract findings (`findings.jsonl`), the file the editor reads.

Evidence is the engine's own bookkeeping: one record per claim, keyed by what it is about.
A finding is one thing to show a developer at one place in their code. The two are not the
same shape — a single signature change is one evidence record and as many findings as there
are call sites that no longer fit — so the mapping lives here rather than leaking into either
side.

Only actionable records become findings. A file that parsed fine and changed no signature is
the normal case and is not news; it stays in the board and out of the editor.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from ..view.index import write_atomic
from . import problems

SCHEMA_VERSION = 1
MAX_DIAGNOSTICS = 20

#: Deterministic parse results are observed; a call the parser could not settle (splat
#: unpacking, for one) is inferred. A record whose inputs have since changed is outdated.
BASIS = {"breaks": "observed", "unsure": "inferred"}


def line(text: object, limit: int = 300) -> str:
    """One line, always. A finding field is rendered as a single row in the editor, and Neovim
    refuses to set a buffer line containing a newline at all — so a multi-line value does not
    render badly, it raises and takes the whole pane down with it.

    Language servers routinely send several lines (basedpyright's "no overloads" explains each
    candidate on its own line) and a model sentence can wrap. Both are legitimate; flattening is
    this boundary's job, not the adapter's.
    """
    return " ".join(str(text or "").split())[:limit]


_COUNT = re.compile(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected)\b")


def outcome(claim: str) -> dict:
    """`passed: 68 passed, 2 skipped in 4.34s` -> status and counts, so the editor can say
    `✓ 68 tests` without parsing pytest's prose itself. A run with no counts (unavailable,
    replay) has an empty `counts`, not a missing one."""
    status, _, summary = claim.partition(":")
    counts: dict[str, int] = {}
    for n, word in _COUNT.findall(summary):
        key = "errors" if word.startswith("error") else word
        counts[key] = counts.get(key, 0) + int(n)
    return {"status": status.strip(), "counts": counts}


def _id(*parts: object) -> str:
    return "f-" + hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:10]


def _revision(based_on: dict, manifest: dict) -> dict:
    """Per path: was the claim derived from the saved file or from an unsaved buffer?"""
    return {p: manifest.get(p, {}).get("origin", "disk") for p in based_on}


def from_record(rec: dict, manifest: dict) -> list[dict]:
    kind, stale = rec["kind"], rec["status"] != "fresh"
    out: list[dict] = []
    if kind in ("signature_change", "removed_function"):
        for loc in rec.get("locations", []):
            if loc["verdict"] not in BASIS:
                continue                       # a call that still fits is not a finding
            out.append({
                "schema_version": SCHEMA_VERSION,
                "id": _id(rec["key"], loc["path"], loc["line"]),
                "kind": "caller_affected",
                "surface": "callers",
                "title": line(rec["title"], 200),
                "basis": "outdated" if stale else BASIS[loc["verdict"]],
                "location": {"path": loc["path"], "line": loc["line"], "col": loc["col"]},
                "consequence": line(loc["reason"], 200),
                "evidence": [{"kind": "snapshot", "ref": loc["file_sha"],
                              "detail": line(loc["text"], 200)}],
                "action": None,
                "depends_on": rec["based_on"],
                "revision": _revision(rec["based_on"], manifest),
                "snapshot_id": rec["fingerprint"],
                "created_ts": rec["ts"],
            })
        if rec.get("suggestion") and out:
            out[0]["evidence"].append({"kind": "model", "ref": "suggestion",
                                       "detail": line(rec["suggestion"])})
    elif kind == "test_run":
        result = outcome(rec["claim"])
        details = rec.get("details", {})
        out.append({
            "schema_version": SCHEMA_VERSION,
            "id": _id(rec["key"]),
            "kind": "test_result",
            "surface": "errors",
            "title": line(rec["title"], 200),
            "basis": "outdated" if stale else "observed",
            "scope": sorted(p for p in rec["based_on"] if p.endswith(".py")),
            "consequence": line(rec["claim"], 200),
            "outcome": result,
            "evidence": [{"kind": "test", "ref": result["status"], "detail": line(v)}
                         for v in (details.get("failed"), details.get("first_error")) if v],
            "action": None,
            "depends_on": rec["based_on"],
            "revision": _revision(rec["based_on"], manifest),
            "saved_revision_only": True,   # pytest runs against the working tree, never a buffer
            "snapshot_id": rec["fingerprint"],
            "created_ts": rec["ts"],
        })
    return out


def checked_fixes(records: list[dict], manifest: dict) -> dict[tuple[str, str], dict]:
    """Fresh fix proposals the gate checked, for the revision the editor is on, by (path, problem).

    A fix is offered only against the exact bytes it was checked on: `depends_on` is what the
    adapter compares before applying, and a revision that moved hides the fix rather than showing
    one computed for other code."""
    out: dict[tuple[str, str], dict] = {}
    for rec in records:
        if rec["kind"] != "fix_proposal" or rec["status"] != "fresh" or rec["claim"] != "checked":
            continue
        (path, sha), = rec["based_on"].items()
        if manifest.get(path, {}).get("sha") != sha:
            continue
        d = rec["details"]
        out[(path, d["problem"])] = {"id": d.get("fix_id") or rec["key"], "verdict": "checked",
                                     "covers": d.get("covers") or [rec["locations"][0]["line"]],
                                     "warnings": d["warnings"], "edits": d["edits"], "diff": d["diff"],
                                     "profile": d["profile"], "depends_on": {path: sha}}
    return out


def from_diagnostics(diagnostics: dict[str, list[dict]], manifest: dict,
                     fixes: dict[tuple[str, str], dict] | None = None) -> list[dict]:
    """The editor's own diagnostics, interpreted rather than echoed: grouped into problems and
    each said as one sentence (`problems.py`), with every raw message kept as evidence. Only
    errors: warnings are already in the sign column and repeating them is noise. A problem with a
    checked fix carries it as `fix`."""
    out: list[dict] = []
    for path in sorted(diagnostics):
        errors = [d for d in diagnostics[path] if d.get("severity") == "error"]
        for problem in problems.group(errors):
            lead = problem.lead
            out.append({
                "schema_version": SCHEMA_VERSION,
                "id": _id("diag", path, lead.get("line"), lead.get("col"), lead.get("message")),
                "kind": "diagnostic_context",
                "surface": "errors",
                "title": line(problem.sentence, 160),
                "facts": {k: line(v, 80) for k, v in problem.facts.items()},
                "diagnostics": len(problem.members),
                "basis": "observed",
                "location": {"path": path, "line": lead.get("line"), "col": lead.get("col"),
                             "end_line": lead.get("end_line"), "end_col": lead.get("end_col")},
                "consequence": line(f"{lead.get('source') or 'language server'}"
                                   + (f" {lead['code']}" if lead.get("code") else ""), 200),
                "evidence": [{"kind": "diagnostic", "ref": d.get("code") or "-",
                              "detail": line(d.get("message"))} for d in problem.members],
                "action": None,
                "depends_on": {p: r["sha"] for p, r in manifest.items() if p == path},
                "revision": {path: manifest.get(path, {}).get("origin", "disk")},
                "snapshot_id": manifest.get(path, {}).get("sha", ""),
                "created_ts": time.time(),
            })
            if (fix := (fixes or {}).get((path, problem.key))) is not None:
                out[-1]["fix"] = fix
            if len(out) >= MAX_DIAGNOSTICS:
                return out
    return out


def build(records: list[dict], manifest: dict, diagnostics: dict[str, list[dict]]) -> list[dict]:
    out: list[dict] = []
    for rec in records:
        out.extend(from_record(rec, manifest))
    out.extend(from_diagnostics(diagnostics, manifest, checked_fixes(records, manifest)))
    return out


def write(out_dir: Path, findings: list[dict]) -> None:
    """Whole-file rewrite, atomically: the reader always sees a complete set, never a mixture
    of the previous one and this one."""
    body = "".join(json.dumps(f, sort_keys=True) + "\n" for f in findings)
    write_atomic(out_dir / "findings.jsonl", body)
