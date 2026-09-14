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
import time
from pathlib import Path

from ..view.index import write_atomic

SCHEMA_VERSION = 1
MAX_DIAGNOSTICS = 20

#: Deterministic parse results are observed; a call the parser could not settle (splat
#: unpacking, for one) is inferred. A record whose inputs have since changed is outdated.
BASIS = {"breaks": "observed", "unsure": "inferred"}


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
                "title": rec["title"],
                "basis": "outdated" if stale else BASIS[loc["verdict"]],
                "location": {"path": loc["path"], "line": loc["line"], "col": loc["col"]},
                "consequence": loc["reason"],
                "evidence": [{"kind": "snapshot", "ref": loc["file_sha"], "detail": loc["text"]}],
                "action": None,
                "depends_on": rec["based_on"],
                "revision": _revision(rec["based_on"], manifest),
                "snapshot_id": rec["fingerprint"],
                "created_ts": rec["ts"],
            })
        if rec.get("suggestion") and out:
            out[0]["evidence"].append({"kind": "model", "ref": "suggestion",
                                       "detail": rec["suggestion"]})
    elif kind == "test_run":
        status = rec["claim"].split(":", 1)[0]
        details = rec.get("details", {})
        out.append({
            "schema_version": SCHEMA_VERSION,
            "id": _id(rec["key"]),
            "kind": "test_result",
            "surface": "errors",
            "title": rec["title"],
            "basis": "outdated" if stale else "observed",
            "scope": sorted(p for p in rec["based_on"] if p.endswith(".py")),
            "consequence": rec["claim"],
            "evidence": [{"kind": "test", "ref": status, "detail": v}
                         for v in (details.get("failed"), details.get("first_error")) if v],
            "action": None,
            "depends_on": rec["based_on"],
            "revision": _revision(rec["based_on"], manifest),
            "saved_revision_only": True,   # pytest runs against the working tree, never a buffer
            "snapshot_id": rec["fingerprint"],
            "created_ts": rec["ts"],
        })
    return out


def from_diagnostics(diagnostics: dict[str, list[dict]], manifest: dict) -> list[dict]:
    """The editor's own diagnostics, echoed back so one pane holds the whole picture. Only
    errors: warnings are already in the sign column and repeating them is noise."""
    out: list[dict] = []
    for path in sorted(diagnostics):
        for d in diagnostics[path]:
            if d.get("severity") != "error":
                continue
            out.append({
                "schema_version": SCHEMA_VERSION,
                "id": _id("diag", path, d.get("line"), d.get("col"), d.get("message")),
                "kind": "diagnostic_context",
                "surface": "errors",
                "title": d.get("message", "").splitlines()[0][:160],
                "basis": "observed",
                "location": {"path": path, "line": d.get("line"), "col": d.get("col")},
                "consequence": f"{d.get('source') or 'language server'}"
                               + (f" {d['code']}" if d.get("code") else ""),
                "evidence": [{"kind": "diagnostic", "ref": d.get("code") or "-",
                              "detail": d.get("message", "")[:300]}],
                "action": None,
                "depends_on": {p: r["sha"] for p, r in manifest.items() if p == path},
                "revision": {path: manifest.get(path, {}).get("origin", "disk")},
                "snapshot_id": manifest.get(path, {}).get("sha", ""),
                "created_ts": time.time(),
            })
            if len(out) >= MAX_DIAGNOSTICS:
                return out
    return out


def build(records: list[dict], manifest: dict, diagnostics: dict[str, list[dict]]) -> list[dict]:
    out: list[dict] = []
    for rec in records:
        out.extend(from_record(rec, manifest))
    out.extend(from_diagnostics(diagnostics, manifest))
    return out


def write(out_dir: Path, findings: list[dict]) -> None:
    """Whole-file rewrite, atomically: the reader always sees a complete set, never a mixture
    of the previous one and this one."""
    body = "".join(json.dumps(f, sort_keys=True) + "\n" for f in findings)
    write_atomic(out_dir / "findings.jsonl", body)
