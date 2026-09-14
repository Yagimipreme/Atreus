"""Presentation: a markdown board and a quickfix file. Nothing pops up; the editor pulls."""
from __future__ import annotations

import time
from pathlib import Path

ORDER = ["signature_change", "removed_function", "test_run", "fix_proposal", "new_function", "unknown_intent",
         "cancelled", "noop"]
HEAD = {
    "signature_change": "Signature changes",
    "removed_function": "Removed functions",
    "test_run": "Tests touched by the change",
    "fix_proposal": "Fix proposals (checked means the gate vouched for it, not that it is right)",
    "new_function": "New functions (test generation not enabled yet)",
    "unknown_intent": "Unknown intent (file mid-edit)",
    "cancelled": "Cancelled (superseded before it finished)",
    "noop": "No useful action",
}


def _age(ts: float) -> str:
    s = int(time.time() - ts)
    return f"{s}s" if s < 90 else f"{s // 60}m"


def render(records: list[dict], root: Path, stats: dict | None = None) -> str:
    fresh = [r for r in records if r["status"] == "fresh"]
    stale = [r for r in records if r["status"] != "fresh"]
    out = [f"# companion board — {root.name}", ""]
    if stats:
        out.append("_" + ", ".join(f"{k}={v}" for k, v in stats.items()) + "_")
        out.append("")
    if not fresh:
        out.append("_nothing fresh to show_")
    for kind in ORDER:
        rs = [r for r in fresh if r["kind"] == kind]
        if not rs:
            continue
        out.append(f"## {HEAD[kind]}")
        if kind == "noop":
            for r in rs:
                out.append(f"- `{r['title']}`: {r['claim']}")
            out.append("")
            continue
        if kind == "fix_proposal":
            for r in rs:
                d, why = r.get("details", {}), r["locations"][0]["reason"] if r["locations"] else ""
                warned = f", {len(d['warnings'])} new warning(s)" if d.get("warnings") else ""
                out.append(f"- `{r['title']}` {r['claim']}{warned}" + (f": {why}" if why else "")
                           + (f" — {d['profile']}" if d.get("profile") else ""))
            out.append("")
            continue
        for r in rs:
            out.append(f"- **{r['title']}** ({_age(r['ts'])} ago)  ")
            out.append(f"  {r['claim']}")
            if r.get("suggestion"):
                out.append(f"  > {r['suggestion']}")
            for l in r["locations"]:
                out.append(f"  - `{l['path']}:{l['line']}` {l['verdict']}: {l['reason']} — `{l['text']}`")
            for k, v in r.get("details", {}).items():
                out.append(f"  - {k}: {v}")
        out.append("")
    if stale:
        out.append("## Stale (input changed since; awaiting re-run)")
        for r in stale[:10]:
            out.append(f"- ~~{r['title']}~~ ({_age(r['ts'])} ago)")
        out.append("")
    return "\n".join(out)


def quickfix(records: list[dict], root: Path) -> str:
    lines = []
    for r in records:
        if r["status"] != "fresh":
            continue
        for l in r["locations"]:
            if l["verdict"] in ("breaks", "unsure"):
                lines.append(f"{root / l['path']}:{l['line']}:{l['col']}: {l['verdict']}: {l['reason']} [{r['title']}]")
    return "\n".join(lines) + ("\n" if lines else "")


def write(root: Path, out_dir: Path, records: list[dict], stats: dict | None = None) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "board.md").write_text(render(records, root, stats))
    (out_dir / "quickfix.txt").write_text(quickfix(records, root))
