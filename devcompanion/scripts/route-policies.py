"""Routing policies over measured replies: what per-function model selection, escalation chains
and a local-only profile would have delivered on the same cases -- computed from stored rows,
calling no model.

  .venv/bin/python scripts/route-policies.py [--fixes docs/evaluations/checked-fixes.json]
      [--functions docs/evaluations/functions.json] [--output docs/evaluations/routing-policies-table.md]
      [--no-swaps]

A chain tries models in order and stops at the first answer its gate accepts. Its latency is the
sum over the models it tried, plus **model swaps**: on this host's 8 GB card the two local models
do not stay loaded together -- loading one evicts the other -- so a chain that moves between them
pays the reload each time, and so does the next case that starts on the other one. The reload
costs are measured (LOAD, weights still in the page cache; a cold 30B load is ~25 s). `--no-swaps`
assumes both resident, as if on a larger card. Every gate is computable at run time, without
knowing the right answer:

  fixes       the checker's verdict: `checked` with no new warning (strict), or `checked` with new
              warnings noted, the rule in force (qualify)
  sentence    the sentence check: names kept, at most 14 words, nothing invented, not an echo of
              the message. It is also how the job is scored, so a chain's shown sentences all pass
              by construction; what it measures is coverage and cost, not quality beyond the check
  culprit     the packet fits the model's context
  suspicious  no gate exists; single models, and "flag only where two models name the same line"
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from devcompanion.llm import providers  # noqa: E402

SMALL = ["qwen2.5-coder:3b", "qwen2.5-coder:3b@gpu=0"]
LARGE = "qwen3-coder:30b"
LOCAL = [*SMALL, LARGE]
# Seconds to bring a model back after the other evicted it: RTX 2080 SUPER 8 GB, Ollama 0.33.3,
# weights in the page cache, 2026-09-14 (3B: 4.39 s and 3.08 s round trips; 30B: 6.24 s). The
# CPU-only 3B stays loaded beside the 30B, so it has no entry and never swaps.
LOAD = {"qwen2.5-coder:3b": 3.6, "qwen3-coder:30b": 5.9}


def nearest(values: list, q: float):
    values = sorted(v for v in values if v is not None)
    return round(values[max(0, math.ceil(q * len(values)) - 1)], 2) if values else None


def short(label: str) -> str:
    return {"qwen2.5-coder:3b": "3B", "qwen2.5-coder:3b@gpu=0": "3B-cpu", LARGE: "30B"}.get(label, label)


def chains(labels: list[str]) -> list[list[str]]:
    small = [l for l in SMALL if l in labels]
    large = [LARGE] if LARGE in labels else []
    remote = [l for l in labels if providers.parse(l).remote]
    out = [[l] for l in small + large + remote]
    out += [[s, *large] for s in small if large]
    for r in remote:
        out += [[l, r] for l in small + large]
        out += [[s, *large, r] for s in small if large]
    return out


def walk(chain, keys, row, accept, right, load):
    shown = wrong = remote_reached = swaps = 0
    spent, cost = [], 0.0
    resident = next((l for l in chain if l in load), None)
    for key in keys:
        seconds, chosen = 0.0, None
        for label in chain:
            r = row.get((label, key))
            if r is None:
                return None
            if label in load and label != resident:
                seconds += load[label]
                swaps += 1
                resident = label
            seconds += (r.get("model_s") or 0) + (r.get("check_s") or 0)
            cost += r.get("cost_usd") or 0
            if providers.parse(label).remote:
                remote_reached += 1
            if accept(r):
                chosen = r
                break
        spent.append(seconds)
        if chosen is not None:
            shown += 1
            wrong += not right(chosen)
    n = len(keys)
    return {"chain": " → ".join(short(l) for l in chain), "n": n, "shown": shown, "right": shown - wrong,
            "wrong": wrong, "p50": nearest(spent, .5), "p90": nearest(spent, .9), "swaps": swaps,
            "remote_share": round(remote_reached / n, 2) if n else 0, "cost": round(cost, 3)}


def table(title: str, note: str, results: list[dict], right_label: str) -> list[str]:
    out = [f"### {title}", "", note, "",
           f"| chain | shown | {right_label} | shown but wrong | seconds p50 / p90 | local model swaps | cases reaching a subscription model | API-equivalent cost $ |",
           "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in results:
        out.append(f"| {r['chain']} | {r['shown']}/{r['n']} | {r['right']} | {r['wrong']} | {r['p50']} / {r['p90']} | "
                   f"{r['swaps']} | {round(r['remote_share'] * 100)}% | {r['cost']} |")
    return out + [""]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixes", type=Path, default=PROJECT / "docs/evaluations/checked-fixes.json")
    ap.add_argument("--functions", type=Path, default=PROJECT / "docs/evaluations/functions.json")
    ap.add_argument("--output", type=Path, default=PROJECT / "docs/evaluations/routing-policies-table.md")
    ap.add_argument("--no-swaps", action="store_true", help="assume both local models stay resident")
    a = ap.parse_args()
    load = {} if a.no_swaps else LOAD
    out = ["# Routing policies — computed from stored replies", "",
           ("Both local models assumed resident." if a.no_swaps else
            f"Local model swaps charged at {LOAD['qwen2.5-coder:3b']} s (3B) and {LOAD['qwen3-coder:30b']} s (30B)."), ""]

    if a.fixes.exists():
        fixes = json.loads(a.fixes.read_text())
        labels = list(fixes["models"])
        row = {(r["model"], r["case"]): r for r in fixes["rows"]}
        keys = list(dict.fromkeys(r["case"] for r in fixes["rows"]))
        qualify = lambda r: r["outcome"] == "checked"  # noqa: E731
        strict = lambda r: qualify(r) and not r["warnings"]  # noqa: E731
        intended = lambda r: r["intent_ok"]  # noqa: E731
        out += ["## Checked fixes", "", "### The warnings rule, per model", "",
                "| model | strict: shown | strict: wrong ✓ | qualify: shown | qualify: wrong ✓ | qualify adds, intended |",
                "|---|---:|---:|---:|---:|---:|"]
        for label in labels:
            s, q = walk([label], keys, row, strict, intended, {}), walk([label], keys, row, qualify, intended, {})
            if s and q:
                out.append(f"| {short(label)} | {s['shown']} | {s['wrong']} | {q['shown']} | {q['wrong']} | "
                           f"{q['right'] - s['right']} of {q['shown'] - s['shown']} |")
        out.append("")
        for name, gate in (("strict", strict), ("qualify", qualify)):
            results = [r for c in chains(labels) if (r := walk(c, keys, row, gate, intended, load))]
            out += table(f"Escalation chains, {name} gate",
                         "A chain moves on when the gate refuses; `right` means the behaviour check passed.",
                         results, "right")

    if a.functions.exists():
        functions = json.loads(a.functions.read_text())
        labels = list(functions["models"])
        row = {(r["model"], f"{r['task']}:{r['case']}"): r for r in functions["rows"]}
        by_task: dict[str, dict[str, None]] = {}
        for r in functions["rows"]:
            by_task.setdefault(r["task"], {})[f"{r['task']}:{r['case']}"] = None
        correct = lambda r: bool(r["correct"])  # noqa: E731
        if "sentence" in by_task:
            gate = lambda r: r["status"] == "ok" and r["correct"]  # noqa: E731
            results = [r for c in chains(labels) if (r := walk(c, list(by_task["sentence"]), row, gate, correct, load))]
            out += ["## Functions", ""] + table("Sentences where the rules run out",
                                                "The gate is the sentence check itself; see the docstring.", results, "pass")
        if "culprit" in by_task:
            sent = lambda r: r["status"] == "ok"  # noqa: E731
            results = [r for c in chains(labels) if (r := walk(c, list(by_task["culprit"]), row, sent, correct, load))]
            out += table("Failing test → culprit function",
                         "A chain moves on only when the packet does not fit the model (or the call failed).",
                         results, "named")
        if "suspicious" in by_task:
            keys = list(by_task["suspicious"])
            out += ["### Most suspicious line", "",
                    "A pair flags a line only when both models name the same one. Within one line counts the "
                    "statement a broken condition guards, which is where the 30B tends to point.", "",
                    "| models | bugs found at the exact line | within one line | untouched functions flagged | seconds p50 |",
                    "|---|---:|---:|---:|---:|"]
            singles = [[l] for l in LOCAL if l in labels] + [[l] for l in labels if providers.parse(l).remote]
            pairs = [[x[0], y[0]] for i, x in enumerate(singles) for y in singles[i + 1:]]
            for combo in singles + pairs:
                found = close = false_flags = 0
                bugs = controls = 0
                spent = []
                swap = sum(load.get(l, 0) for l in combo) if sum(l in load for l in combo) == 2 else 0
                for key in keys:
                    rs = [row.get((label, key)) for label in combo]
                    if any(r is None for r in rs):
                        break
                    spent.append(sum(r["model_s"] or 0 for r in rs) + swap)
                    lines = {r["flagged"] for r in rs}
                    flagged = rs[0]["flagged"] if len(lines) == 1 else None
                    if rs[0]["bug"]:
                        bugs += 1
                        found += flagged is not None and all(r["correct"] for r in rs)
                        close += flagged is not None and all(r["correct"] or r.get("near") for r in rs)
                    else:
                        controls += 1
                        false_flags += flagged is not None
                else:
                    name = " ∧ ".join(short(l) for l in combo)
                    out.append(f"| {name} | {found}/{bugs} | {close}/{bugs} | {false_flags}/{controls} | {nearest(spent, .5)} |")
            out.append("")
    a.output.write_text("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
