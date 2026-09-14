"""Hit rates for the chatty functions on qwen3-coder:30b, judged by hand.

The functions are src/devcompanion/pulled/chatty.py. The cases are testing/chatty/ -- explain.py,
grill.py, plan.py, and changes.diff for both summary and commit. A case runs from its `# %% <id>`
line to the next; `# goal:` and `# path:` lines go into the packet, `# expect:` lines are what the
reply is judged against and are never sent. Every run and judgment is appended to
docs/evaluations/chatty-functions.jsonl.

Measured prompts are the local ones (`chatty.SYSTEM`). The flagship's own prompts are not
benchmarked. Runs judged under an earlier prompt stay in the log and stop counting, among them the
one-question grill asked in two turns (`grill/<id>@2`).

  .venv/bin/python scripts/chatty.py run [--only FUNCTION] [--again]   every case; skips a case
                                                    already answered under the current prompt
  .venv/bin/python scripts/chatty.py replies        replies beside their expectations, Markdown
  .venv/bin/python scripts/chatty.py judge RUN LABEL [NOTE]
  .venv/bin/python scripts/chatty.py report         judgments against the bar
  .venv/bin/python scripts/chatty.py ask < item.json  one reply, for testing/chatty/chatty.lua

Labels: good -- usable as it stands; fixable -- hits the expected point and states nothing false,
but needs editing; unusable -- misses the point, states something false, or invents a problem in a
control case. The bar, set before the first run: a group with more than one unusable case is
unusable on the 30B and is routed to the flagship, which is not benchmarked on it.

Local only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from devcompanion.llm import providers  # noqa: E402
from devcompanion.pulled import chatty  # noqa: E402

LOG = PROJECT / "docs/evaluations/chatty-functions.jsonl"
CASE_DIR = PROJECT / "testing/chatty"
CASE_FILES = {"explain.py": ("explain",), "grill.py": ("grill",), "plan.py": ("plan",),
              "changes.diff": ("summary", "commit")}
MODEL = "qwen3-coder:30b"
LABELS = ("good", "fixable", "unusable")
CASES = 6
MAX_UNUSABLE = 1

MARKER = re.compile(r"^# %%\s*(\S+)")
META = re.compile(r"^#\s*(expect|goal|path):\s*(.*)$")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append(row: dict) -> None:
    with LOG.open("a") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def rows() -> list[dict]:
    if not LOG.exists():
        return []
    return [json.loads(line) for line in LOG.read_text().splitlines() if line.strip()]


def split(lines: list[str]) -> tuple[str, dict[str, list[str]]]:
    body: list[str] = []
    meta: dict[str, list[str]] = {"expect": [], "goal": [], "path": []}
    for line in lines:
        m = META.match(line)
        if m:
            meta[m.group(1)].append(m.group(2))
        elif not MARKER.match(line):
            body.append(line)
    return "\n".join(body).strip("\n"), meta


def cases():
    """(function, case id, lines) for every case, in file order."""
    for name, functions in CASE_FILES.items():
        blocks: list[tuple[str, list[str]]] = []
        for line in (CASE_DIR / name).read_text().splitlines():
            m = MARKER.match(line)
            if m:
                blocks.append((m.group(1), []))
            elif blocks:
                blocks[-1][1].append(line)
        for case, lines in blocks:
            for function in functions:
                yield function, f"{Path(name).stem}/{case}", lines


def group(function: str, case: str) -> str:
    return f"{function} @2" if case.endswith("@2") else function


def groups() -> list[str]:
    return list(chatty.FUNCTIONS)


def ask_item(item: dict, model: str) -> dict:
    function = item["function"]
    spec = providers.parse(model)
    if spec.remote:
        sys.exit("chatty.py measures the local model only")
    spec = replace(spec, tokens=chatty.TOKENS[function])
    text, meta = split(item["lines"])
    goal = item.get("goal") or " ".join(meta["goal"])
    path = meta["path"][0] if meta["path"] else item.get("path", "")
    history = [tuple(pair) for pair in item.get("history") or []]
    system = chatty.SYSTEM[function]
    user = chatty.packet(function, text, path, goal, history)
    run = {"kind": "run", "id": uuid.uuid4().hex[:8], "at": now(), "function": function,
           "case": item.get("case") or "adhoc", "turn": len(history) + 1, "prompt": chatty.prompt_id(function),
           "model": model, "expect": meta["expect"], "history": history, "user": user}
    if function == "plan" and not goal:
        run.update(status="plan needs a goal", reply=None, gen_tokens=None, truncated=False)
    elif chatty.estimated_tokens(system, user) > spec.ctx - spec.tokens - 64:
        run.update(status="too_large", reply=None, gen_tokens=None, truncated=False)
    else:
        reply = providers.ask(spec, system, user, timeout_s=240)
        run.update(status=reply.status, reply=reply.text, gen_tokens=reply.gen_tokens,
                   truncated=bool(reply.gen_tokens and reply.gen_tokens >= spec.tokens))
        if function == "commit" and reply.text:
            run["shaped"] = chatty.shape_commit(reply.text)
    append(run)
    return run


def current(model: str) -> tuple[dict[tuple[str, str], dict], dict[str, dict]]:
    """The latest answered run of each case under the current prompt, and the latest judgment of each run."""
    latest: dict[tuple[str, str], dict] = {}
    judgments: dict[str, dict] = {}
    for r in rows():
        if r["kind"] == "judgment":
            judgments[r["run"]] = r
        elif (r["case"] != "adhoc" and r["status"] == "ok" and r["model"] == model
              and r["prompt"] == chatty.prompt_id(r["function"])):
            latest[(r["function"], r["case"])] = r
    return latest, judgments


def ask(args) -> None:
    print(json.dumps(ask_item(json.load(sys.stdin), args.model), ensure_ascii=False))


def say(r: dict) -> dict:
    detail = f" · {r['gen_tokens']} tokens" + (" · cut" if r["truncated"] else "") if r["status"] == "ok" else ""
    print(f"{r['function']:<8} {r['case']:<36} {r['id']} {r['status']}{detail}", flush=True)
    return r


def run_all(args) -> None:
    latest, _ = current(args.model)
    for function, case, lines in cases():
        if (args.only and function not in args.only) or ((function, case) in latest and not args.again):
            continue
        say(ask_item({"function": function, "case": case, "lines": lines}, args.model))


def replies(args) -> None:
    latest, judgments = current(args.model)
    for name in groups():
        print(f"## {name}\n")
        for (f, case), run in latest.items():
            if group(f, case) != name:
                continue
            print(f"### {case} · `{run['id']}`\n")
            for e in run["expect"]:
                print(f"*Expected:* {e}\n")
            for q, a in run.get("history") or []:
                print(f"*After:* {q} → *{a}*\n")
            print(f"````\n{run['reply']}\n````\n")
            if run.get("shaped"):
                s = run["shaped"]
                print(f"*Shaped:* subject `{s['subject']}`" + "".join(f" · {p}" for p in s["problems"]) + "\n")
            if run["truncated"]:
                print("*Cut at the token limit.*\n")
            if run["id"] in judgments:
                j = judgments[run["id"]]
                print(f"*Judged:* {j['label']}" + (f" -- {j['note']}" if j["note"] else "") + "\n")


def judge(args) -> None:
    if not any(r["kind"] == "run" and r["id"] == args.run for r in rows()):
        sys.exit(f"no run {args.run}")
    append({"kind": "judgment", "run": args.run, "label": args.label, "note": args.note, "at": now()})


def report(args) -> None:
    latest, judgments = current(args.model)
    print(f"{'group':<9} {'good':>4} {'fixable':>7} {'unusable':>8} {'judged':>6}  verdict (bar: at most "
          f"{MAX_UNUSABLE} unusable)")
    details = []
    for name in groups():
        runs = [(case, run) for (f, case), run in latest.items() if group(f, case) == name]
        counts: Counter = Counter()
        for case, run in runs:
            if run["id"] not in judgments:
                continue
            j = judgments[run["id"]]
            counts[j["label"]] += 1
            if j["label"] != "good":
                details.append(f"  {case}: {j['label']}" + (f" -- {j['note']}" if j["note"] else ""))
        judged = sum(counts.values())
        if counts["unusable"] > MAX_UNUSABLE:
            verdict = "unusable on the 30B -> flagship"
        elif judged < len(runs):
            verdict = f"{len(runs) - judged} to judge"
        elif not runs:
            verdict = "not run under the current prompt"
        else:
            verdict = "usable on the 30B"
        print(f"{name:<9} {counts['good']:>4} {counts['fixable']:>7} {counts['unusable']:>8} "
              f"{judged:>3}/{len(runs)}  {verdict}")
    if details:
        print("\nnot good:")
        print("\n".join(details))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=MODEL)
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("--only", action="append", choices=chatty.FUNCTIONS)
    r.add_argument("--again", action="store_true", help="ask again cases already answered")
    r.set_defaults(handler=run_all)
    sub.add_parser("replies").set_defaults(handler=replies)
    sub.add_parser("ask").set_defaults(handler=ask)
    j = sub.add_parser("judge")
    j.add_argument("run")
    j.add_argument("label", choices=LABELS)
    j.add_argument("note", nargs="?", default="")
    j.set_defaults(handler=judge)
    sub.add_parser("report").set_defaults(handler=report)
    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
