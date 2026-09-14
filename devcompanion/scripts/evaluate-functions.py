"""Function scope: which model can do which companion job, measured on problems taken from this
project's own committed code (tests/fixtures/function-corpus.json, from
scripts/build-function-corpus.py).

  .venv/bin/python scripts/evaluate-functions.py --model qwen2.5-coder:3b --model qwen3-coder:30b \
      --output docs/evaluations/functions.json
  .venv/bin/python scripts/evaluate-functions.py --append --jobs 3 --model claude:sonnet/low \
      --model claude:opus/medium --model codex: --output docs/evaluations/functions.json
  .venv/bin/python scripts/evaluate-functions.py --rescore docs/evaluations/functions.json

Three jobs, each scored without a human:

  sentence   passive. Rewrite a checker message that no rule covers as one short sentence. Passes
             when the first three short quoted names or types in the message survive verbatim (a
             `Literal[...]` may become its plain type), the sentence has at most 14 words, and it
             puts nothing in backticks that is not in the message or the code line.
  suspicious pulled, one function. Either a planted bug the checker cannot see or an untouched
             function. The answer is `line N: reason` or `none`. A bug counts as found only at its
             exact line; an untouched function counts as right only for `none`.
  culprit    pulled, several files. A failing test's output, the functions its traceback passes
             through, and six recently changed functions of which one holds the planted bug; the
             answer names that function. A packet that does not fit a local model's context is
             not sent to it, counts as a miss, and is reported apart.

Model specs are llm/providers.py's. A remote spec sends this project's committed source -- public
on GitHub -- to that provider, and nothing else.
"""
from __future__ import annotations

import argparse
import difflib
import json
import math
import re
import sys
import threading
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from devcompanion.llm import providers  # noqa: E402
from devcompanion.present.problems import first_line, simplify_type  # noqa: E402

API = "http://127.0.0.1:11434"
TASKS = ("sentence", "suspicious", "culprit")
TOKENS = {"sentence": 60, "suspicious": 60, "culprit": 80}

SYSTEM = {
    "sentence": ("You turn type-checker messages into one short sentence a developer reads at a glance: "
                 "at most 12 words, names and types exactly as written and in backticks. "
                 "No preamble, no advice."),
    "suspicious": ("You review one Python function for a bug. Lines are numbered. If one line is most likely "
                   "wrong, reply `line N: reason`, the reason in at most 12 words. If nothing looks wrong, "
                   "reply `none`. Reply with nothing else."),
    "culprit": ("A test started failing after recent changes. From its output, the functions its traceback "
                "passes through, and the functions changed since it last passed, name the one function most "
                "likely to contain the bug. Reply `path::function` on the first line, then at most one "
                "sentence of reason."),
}


def shown(functions: list[dict]) -> str:
    return "\n\n".join(f"### {p['path']}::{p['name']}\n```python\n{p['source']}\n```" for p in functions) or "(none)"


def cases(corpus: dict) -> list[dict]:
    out = []
    for s in corpus["sentences"]:
        out.append({"task": "sentence", "id": s["id"], "case": s,
                    "user": f"Rule: {s['rule']}\nMessage: {s['message']}\nCode: {s['code_line']}"})
    for m in [*corpus["mutations"], *corpus["controls"]]:
        source = m.get("mutated_source", m["source"])
        numbered = "\n".join(f"{i:>3}| {line}" for i, line in enumerate(source.splitlines(), 1))
        out.append({"task": "suspicious", "id": m["id"], "case": m, "user": f"File: {m['path']}\n\n{numbered}"})
    for m in corpus["mutations"]:
        p = m["packet"]
        out.append({"task": "culprit", "id": m["id"], "case": m,
                    "user": (f"Failure:\n```\n{m['failure']}\n```\n\n"
                             f"Functions the traceback passes through:\n\n{shown(p['trace'])}\n\n"
                             f"Functions changed since the test last passed:\n\n{shown(p['changed'])}")})
    return out


def score(item: dict, reply: str | None) -> dict:
    text = (reply or "").strip()
    c = item["case"]
    if item["task"] == "sentence":
        quoted = list(dict.fromkeys(re.findall(r'"([^"]{1,40})"', c["message"])))[:3]
        kept = [q for q in quoted if q in text or simplify_type(q) in text]
        allowed = c["message"] + " " + c["code_line"] + " " + " ".join(simplify_type(q) for q in quoted)
        invented = [t for t in re.findall(r"`([^`]+)`", text) if t not in allowed]
        words = len(text.split())
        # Repeating the checker's own first line is not an interpretation, however short it is.
        plain = lambda s: re.sub(r"[`\"'.]", "", s).lower().strip()  # noqa: E731
        echo = difflib.SequenceMatcher(None, plain(text), plain(first_line(c["message"]))).ratio() >= 0.8
        ok = bool(text) and len(kept) == len(quoted) and words <= 14 and not invented and not echo
        return {"correct": ok, "answer": text[:160], "kept": f"{len(kept)}/{len(quoted)}",
                "words": words, "invented": invented[:3], "echo": echo}
    if item["task"] == "suspicious":
        line = re.search(r"\bline\s+(\d+)", text, flags=re.I)
        flagged = int(line.group(1)) if line else None
        says_none = flagged is None and bool(re.match(r"[`*\s]*none\b", text, flags=re.I))
        if "line_in_function" in c:
            return {"correct": flagged == c["line_in_function"], "answer": text[:160], "bug": True,
                    "flagged": flagged, "near": flagged is not None and abs(flagged - c["line_in_function"]) == 1,
                    "said_none": says_none}
        return {"correct": says_none, "answer": text[:160], "bug": False, "flagged": flagged, "said_none": says_none}
    named = re.search(r"([\w./-]+\.py)::(\w+)", text)
    functions = [*c["packet"]["trace"], *c["packet"]["changed"]]
    name = named.group(2) if named else next((p["name"] for p in functions if re.search(rf"\b{p['name']}\b", text)), None)
    return {"correct": name == c["function"], "answer": text[:160], "named": name}


def call(path: str, body: dict | None = None, timeout: float = 10) -> dict:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(API + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def nearest(values: list, q: float):
    values = sorted(v for v in values if v is not None)
    return round(values[max(0, math.ceil(q * len(values)) - 1)], 2) if values else None


def run_item(spec: providers.Spec, label: str, item: dict) -> dict:
    system, user = SYSTEM[item["task"]], item["user"]
    row = {"model": label, "task": item["task"], "case": item["id"],
           "estimated_tokens": round((len(system) + len(user)) / 3.2)}
    if not spec.remote:
        spec = replace(spec, tokens=TOKENS[item["task"]])
        if row["estimated_tokens"] > spec.ctx - spec.tokens - 64:
            return {**row, "status": "too_large", "model_s": None, "prompt_tokens": None, "gen_tokens": None,
                    "cost_usd": None, "reply": None, **score(item, None)}
    reply = providers.ask(spec, system, user, timeout_s=300)
    truncated = (not spec.remote and reply.prompt_tokens is not None
                 and reply.prompt_tokens >= spec.ctx - spec.tokens - 8)
    return {**row, "status": reply.status, "served_by": reply.model, "model_s": round(reply.wall_s, 3),
            "prompt_tokens": reply.prompt_tokens, "gen_tokens": reply.gen_tokens, "cost_usd": reply.cost_usd,
            "truncated": truncated, "reply": reply.text, **score(item, reply.text)}


def summarise(rows: list[dict]) -> dict:
    out = {}
    for task in TASKS:
        rs = [r for r in rows if r["task"] == task]
        if not rs:
            continue
        s = {"cases": len(rs), "correct": sum(r["correct"] for r in rs),
             "statuses": dict(Counter(r["status"] for r in rs)),
             "model_s_p50": nearest([r["model_s"] for r in rs], .5),
             "model_s_p90": nearest([r["model_s"] for r in rs], .9),
             "prompt_tokens_p50": nearest([r["prompt_tokens"] for r in rs], .5),
             "gen_tokens_p50": nearest([r["gen_tokens"] for r in rs], .5),
             "cost_usd": round(sum(r.get("cost_usd") or 0 for r in rs), 4)}
        if task == "suspicious":
            bugs = [r for r in rs if r["bug"]]
            clean = [r for r in rs if not r["bug"]]
            flags = [r for r in rs if r["flagged"] is not None]
            s.update(bugs=len(bugs), bugs_found=sum(r["correct"] for r in bugs),
                     near_misses=sum(r["near"] for r in bugs), controls=len(clean),
                     controls_clean=sum(r["correct"] for r in clean),
                     flags=len(flags), flags_right=sum(r["correct"] for r in flags))
        if task == "culprit":
            sent = [r for r in rs if r["status"] != "too_large"]
            s.update(too_large=len(rs) - len(sent), sent=len(sent), correct_of_sent=sum(r["correct"] for r in sent),
                     truncated=sum(bool(r.get("truncated")) for r in rs),
                     estimated_tokens_p50=nearest([r["estimated_tokens"] for r in rs], .5))
        out[task] = s
    return out


def report(result: dict) -> str:
    out = []
    head = {"sentence": "| model | passes | model s p50 / p90 | tokens in / out |",
            "suspicious": "| model | bugs found at the exact line | ±1 line | untouched functions left alone | flags that were right | model s p50 / p90 |",
            "culprit": "| model | culprit named | of the packets sent | not sent: too large | model s p50 / p90 | tokens in p50 |"}
    for task in TASKS:
        rows = []
        for label, info in result["models"].items():
            s = info.get("summary", {}).get(task)
            if not s:
                continue
            timing = f"{s['model_s_p50']} / {s['model_s_p90']}"
            if task == "sentence":
                rows.append(f"| {label} | {s['correct']}/{s['cases']} | {timing} | {s['prompt_tokens_p50']} / {s['gen_tokens_p50']} |")
            elif task == "suspicious":
                rows.append(f"| {label} | {s['bugs_found']}/{s['bugs']} | {s['near_misses']} | "
                            f"{s['controls_clean']}/{s['controls']} | {s['flags_right']}/{s['flags']} | {timing} |")
            else:
                rows.append(f"| {label} | {s['correct']}/{s['cases']} | {s['correct_of_sent']}/{s['sent']} | "
                            f"{s['too_large']} | {timing} | {s['prompt_tokens_p50']} |")
        if rows:
            out += [f"### {task}", "", head[task], "|" + "---|" * (head[task].count("|") - 1), *rows, ""]
    return "\n".join(out)


def finish(result: dict, output: Path) -> None:
    for label, info in result["models"].items():
        info["summary"] = summarise([r for r in result["rows"] if r["model"] == label])
    output.write_text(json.dumps(result, indent=2))
    table = report(result)
    output.with_name(output.stem + "-table.md").write_text(table + "\n")
    print("\n" + table)
    print(f"Raw results: {output}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", action="append", default=[], help="a providers.py spec")
    ap.add_argument("--corpus", type=Path, default=PROJECT / "tests/fixtures/function-corpus.json")
    ap.add_argument("--task", action="append", choices=TASKS, help="only these tasks")
    ap.add_argument("--limit", type=int, help="at most this many cases per task")
    ap.add_argument("--append", action="store_true")
    ap.add_argument("--rescore", type=Path, help="score the replies a results file already holds")
    ap.add_argument("--jobs", type=int, default=1, help="concurrent cases for a remote model")
    ap.add_argument("--output", type=Path, default=Path("/tmp/devcompanion-functions.json"))
    a = ap.parse_args()

    corpus = json.loads(a.corpus.read_text())
    items = [i for i in cases(corpus) if not a.task or i["task"] in a.task]
    if a.limit:
        seen: Counter = Counter()
        items = [i for i in items if (seen.update([i["task"]]) or True) and seen[i["task"]] <= a.limit]
    if a.rescore:
        result = json.loads(a.rescore.read_text())
        by_id = {(i["task"], i["id"]): i for i in cases(corpus)}
        for row in result["rows"]:
            row.update(score(by_id[(row["task"], row["case"])], row["reply"]))
        finish(result, a.rescore)
        return
    if not a.model:
        raise SystemExit("--model is required unless --rescore")
    if a.append and a.output.exists():
        result = json.loads(a.output.read_text())
        if result["source_commit"] != corpus["source_commit"] or result.get("corpus_generated_at") != corpus["generated_at"]:
            raise SystemExit(f"{a.output} was measured on a different corpus build")
    else:
        result = {"timestamp": time.time(), "corpus": str(a.corpus.relative_to(PROJECT)),
                  "source_commit": corpus["source_commit"], "corpus_generated_at": corpus["generated_at"],
                  "temperature_local": 0, "counts": dict(Counter(i["task"] for i in items)),
                  "models": {}, "rows": []}
    specs = [(text, providers.parse(text)) for text in a.model]
    last_local = max((n for n, (_, s) in enumerate(specs) if not s.remote), default=-1)
    lock = threading.Lock()
    for n, (label, spec) in enumerate(specs):
        # A run that stopped part-way (it was once killed for memory) resumes with the cases it lacks.
        done = {(r["task"], r["case"]) for r in result["rows"] if r["model"] == label}
        todo = [i for i in items if (i["task"], i["id"]) not in done]
        if not todo:
            print(f"{label}: complete in {a.output}; remove its rows there to measure again")
            continue
        if done:
            print(f"{label}: resuming, {len(todo)} of {len(items)} cases left")
        info = result["models"].setdefault(label, {"backend": spec.backend, "model": spec.model, "effort": spec.effort,
                                                   "ctx": None if spec.remote else spec.ctx, "measured_at": time.time()})
        if done:
            info["resumed_at"] = time.time()
        keep = spec.keep_alive if n == last_local else "10m"
        if not spec.remote:
            spec = replace(spec, keep_alive=keep)
            t = time.monotonic()
            # Warm with the same placement the calls will ask for, or a CPU-only model loads on the
            # GPU first and evicts whatever holds the card.
            options = {"num_ctx": spec.ctx, **({"num_gpu": spec.gpu} if spec.gpu is not None else {})}
            call("/api/generate", {"model": spec.model, "prompt": "", "stream": False, "keep_alive": keep,
                                   "options": options}, timeout=300)
            info["load_s"] = round(time.monotonic() - t, 2)
        print(f"\n{label}", flush=True)
        with ThreadPoolExecutor(max_workers=a.jobs if spec.remote else 1) as pool:
            futures = [pool.submit(run_item, spec, label, item) for item in todo]
            for future in futures:
                row = future.result()
                with lock:
                    result["rows"].append(row)
                    a.output.write_text(json.dumps(result, indent=2))
                print(f"  {row['task']:10} {row['case']:12} {'✓' if row['correct'] else '·'} "
                      f"{row['model_s'] if row['model_s'] is not None else '-':>6} {row['status']:9} "
                      f"{(row['answer'] or '')[:70]!r}", flush=True)
        if not spec.remote and n != last_local:
            call("/api/generate", {"model": spec.model, "keep_alive": 0}, timeout=60)
    finish(result, a.output)


if __name__ == "__main__":
    main()
