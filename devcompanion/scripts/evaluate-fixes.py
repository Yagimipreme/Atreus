"""Checked fixes: how often a model's proposal survives the checker, and whether what survives is
what the code meant.

  .venv/bin/python scripts/evaluate-fixes.py --check-corpus
  .venv/bin/python scripts/evaluate-fixes.py --model qwen2.5-coder:3b --model qwen3-coder:30b \
      --output docs/evaluations/checked-fixes.json
  .venv/bin/python scripts/evaluate-fixes.py --append --jobs 3 --model claude:sonnet/low \
      --model claude:opus/medium --model codex: --output docs/evaluations/checked-fixes.json
  .venv/bin/python scripts/evaluate-fixes.py --rejudge docs/evaluations/checked-fixes.json

The corpus (tests/fixtures/fix-corpus.txt) holds working modules, each with a mutation that breaks
it and a behaviour check that separates the intended fix from a merely type-correct one. It is
written by hand, not collected from use; docs/evaluations/checked-fixes.md says what that limits.
A case is used only if its working code has no errors, the mutation adds a diagnostic, the working
code passes its check and the broken code fails it.

Model specs are llm/providers.py's: a bare name or `ollama:` is local Ollama (`@tokens=2048`,
`@ctx=16384`); `claude:<alias>[/effort]` and `codex:[model][/effort]` are the subscription CLIs,
run tool-less or read-only in an empty scratch directory. A remote spec sends the corpus -- code
written for this evaluation, nothing from any project -- to that provider. Local models run in
the order given, one resident at a time; the last stays resident for the engine. `--jobs` runs a
remote model's cases concurrently. Behaviour checks execute patched code in a scratch directory.

`--rejudge` re-runs the checker and the behaviour checks over the replies a results file already
holds, calling no model, so a change to how replies are judged is measured on the same output.
"""
from __future__ import annotations

import argparse
import ast
import json
import math
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from devcompanion.fix import check, prompt  # noqa: E402
from devcompanion.llm import providers  # noqa: E402
from devcompanion.present.problems import flat, group  # noqa: E402

API = "http://127.0.0.1:11434"


@dataclass
class Case:
    name: str
    kind: str
    module: str                                        # the working code
    broken: str                                        # the same code after the mutation
    behaviour: str                                     # the check, never shown to model or checker
    before: list[dict] = field(default_factory=list)   # every diagnostic of the broken code
    targets: list[dict] = field(default_factory=list)  # the ones the mutation introduced

    @property
    def file(self) -> str:
        return self.name.replace("-", "_") + ".py"


def load(path: Path) -> list[Case]:
    cases = []
    for chunk in re.split(r"^=== ", path.read_text(), flags=re.M)[1:]:
        head, _, rest = chunk.partition("\n")
        name, _, kind = (part.strip() for part in head.partition(" · "))
        spec, _, body = rest.partition("---\n")
        code, _, behaviour = body.partition("--- check ---\n")
        module = code.rstrip("\n") + "\n"
        broken = module
        for old, new in re.findall(r"^ *break: ?(.*)\n *to: ?(.*)$", spec, flags=re.M):
            old, new = old.replace("\\n", "\n"), new.replace("\\n", "\n")
            if broken.count(old) != 1:
                raise SystemExit(f"{name}: the mutation must match once; it matches {broken.count(old)} times")
            broken = broken.replace(old, new)
        if broken == module:
            raise SystemExit(f"{name}: no mutation")
        cases.append(Case(name, kind, module, broken, behaviour))
    return cases


def behaves(code: str | None, behaviour: str) -> bool:
    if code is None:
        return False
    with tempfile.TemporaryDirectory(prefix="companion-intent-") as tmp:
        script = Path(tmp) / "case.py"
        script.write_text(code + "\n" + behaviour)
        try:
            run = subprocess.run([sys.executable, "-I", str(script)], cwd=tmp,
                                 capture_output=True, timeout=10)
        except subprocess.TimeoutExpired:
            return False
        return run.returncode == 0


def same_code(a: str | None, b: str) -> bool:
    try:
        return a is not None and ast.dump(ast.parse(a)) == ast.dump(ast.parse(b))
    except SyntaxError:
        return False


def prepare(cases: list[Case], binary: str) -> dict[str, list[str]]:
    """Diagnose all working and all broken code in one checker run each; say which cases are not
    a real, discriminating break."""
    working = check.diagnose({f"working/{c.file}": c.module for c in cases}, binary)
    broken = check.diagnose({f"broken/{c.file}": c.broken for c in cases}, binary)
    invalid = {}
    for c in cases:
        good = working[f"working/{c.file}"]
        c.before = broken[f"broken/{c.file}"]
        c.targets = check.introduced(good, c.before)
        why = [f"working code has an error: {flat(d['message'])[:100]}"
               for d in good if d["severity"] == "error"][:1]
        if not c.targets:
            why.append("the mutation adds no diagnostic")
        if not behaves(c.module, c.behaviour):
            why.append("working code fails its check")
        if behaves(c.broken, c.behaviour):
            why.append("broken code passes its check")
        if why:
            invalid[c.name] = why
    return invalid


def judged(c: Case, reply: str | None, binary: str) -> dict:
    """Everything about a row that follows from the reply alone."""
    verdict = check.judge(c.file, c.broken, reply or "", c.targets, c.before, binary)
    return {"outcome": verdict.outcome, "detail": verdict.detail, "form": verdict.form,
            "loose": verdict.loose, "check_s": round(verdict.seconds, 3),
            "remaining": [flat(d["message"]) for d in verdict.remaining],
            "new": [flat(d["message"]) for d in verdict.new],
            "new_errors": len(verdict.new),
            "warnings": [flat(d["message"]) for d in verdict.warnings],
            "intent_ok": behaves(verdict.text, c.behaviour),
            "same_as_working": same_code(verdict.text, c.module)}


def call(path: str, body: dict | None = None, timeout: float = 10) -> dict:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(API + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def nearest(values: list, q: float):
    values = sorted(v for v in values if v is not None)
    return round(values[max(0, math.ceil(q * len(values)) - 1)], 2) if values else None


def summarise(rows: list[dict]) -> dict:
    shown = [r for r in rows if r["outcome"] == "checked"]
    refused = [r for r in rows if r["outcome"] != "checked"]
    warned = [r for r in shown if r.get("warnings")]
    checked_runs = [r["check_s"] for r in rows if r["outcome"] not in ("no_patch", "unparsable", "suppressed")]
    return {
        "cases": len(rows),
        "checked": len(shown),
        "checked_intended": sum(r["intent_ok"] for r in shown),
        "checked_not_intended": sum(not r["intent_ok"] for r in shown),
        "refused_intended": sum(r["intent_ok"] for r in refused),
        "checked_with_new_warnings": len(warned),
        "checked_with_new_warnings_intended": sum(r["intent_ok"] for r in warned),
        "intended_without_checker": sum(r["intent_ok"] for r in rows),
        "same_as_working": sum(r["same_as_working"] for r in rows),
        "outcomes": dict(Counter(r["outcome"] for r in rows)),
        "statuses": dict(Counter(r["status"] for r in rows)),
        "forms": dict(Counter(r["form"] or "none" for r in rows)),
        "loose_patches": sum(r["loose"] for r in rows),
        "model_s_p50": nearest([r["model_s"] for r in rows], .5),
        "model_s_p90": nearest([r["model_s"] for r in rows], .9),
        "check_s_p50": nearest(checked_runs, .5),
        "prompt_tokens_p50": nearest([r["prompt_tokens"] for r in rows], .5),
        "gen_tokens_p50": nearest([r["gen_tokens"] for r in rows], .5),
        "cost_usd": round(sum(r.get("cost_usd") or 0 for r in rows), 4),
    }


def report(result: dict) -> str:
    models = list(result["models"])
    out = ["| model | load s | ✓ shown | ✓ intended | ✓ not intended | intended but refused | "
           "✓ with a new warning (intended) | intended, no checker | model s p50 / p90 | "
           "check s p50 | tokens in / out |",
           "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for m in models:
        s, n = result["models"][m]["summary"], result["cases"]
        out.append(f"| {m} | {result['models'][m].get('load_s', '—')} | {s['checked']}/{n} | "
                   f"{s['checked_intended']} | {s['checked_not_intended']} | {s['refused_intended']} | "
                   f"{s['checked_with_new_warnings']} ({s['checked_with_new_warnings_intended']}) | "
                   f"{s['intended_without_checker']}/{n} | {s['model_s_p50']} / {s['model_s_p90']} | "
                   f"{s['check_s_p50']} | {s['prompt_tokens_p50']} / {s['gen_tokens_p50']} |")
    out += ["", "`✓` checked and intended · `!` checked, not intended · `○` refused, would have been "
            "right · `·` refused, wrong", "", "| case | kind | " + " | ".join(models) + " |",
            "|---|---|" + "---|" * len(models)]
    by = {(r["model"], r["case"]): r for r in result["rows"]}
    for name, kind in dict.fromkeys((r["case"], r["kind"]) for r in result["rows"]):
        cells = []
        for m in models:
            r = by.get((m, name))
            if r is None:
                cells.append("")
                continue
            glyph = ("✓" if r["intent_ok"] else "!") if r["outcome"] == "checked" else ("○" if r["intent_ok"] else "·")
            cells.append(glyph if r["outcome"] == "checked" else f"{glyph} {r['outcome']}")
        out.append(f"| {name} | {kind} | " + " | ".join(cells) + " |")
    return "\n".join(out)


def finish(result: dict, output: Path) -> None:
    for label, info in result["models"].items():
        info["summary"] = summarise([r for r in result["rows"] if r["model"] == label])
    output.write_text(json.dumps(result, indent=2))
    table = report(result)
    output.with_name(output.stem + "-table.md").write_text(table + "\n")
    print("\n" + table)
    print(f"\nRaw results: {output}")


def run_case(spec: providers.Spec, label: str, c: Case, binary: str) -> dict:
    packet = prompt.build(c.file, c.broken, group(c.targets))
    reply = providers.ask(spec, prompt.SYSTEM, packet, timeout_s=300)
    return {"model": label, "case": c.name, "kind": c.kind, "status": reply.status,
            "served_by": reply.model, "remote": spec.remote,
            "model_s": round(reply.wall_s, 3), "prompt_tokens": reply.prompt_tokens,
            "gen_tokens": reply.gen_tokens, "prompt_s": reply.prompt_s, "gen_s": reply.gen_s,
            "cost_usd": reply.cost_usd, **judged(c, reply.text, binary), "human_ok": None,
            "prompt": packet, "reply": reply.text}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", action="append", default=[], help="a providers.py spec")
    ap.add_argument("--corpus", type=Path, default=PROJECT / "tests/fixtures/fix-corpus.txt")
    ap.add_argument("--only", help="regular expression over case names")
    ap.add_argument("--check-corpus", action="store_true")
    ap.add_argument("--rejudge", type=Path, help="results file whose stored replies to judge again")
    ap.add_argument("--append", action="store_true", help="add models to an existing --output")
    ap.add_argument("--jobs", type=int, default=1, help="concurrent cases for a remote model")
    ap.add_argument("--output", type=Path, default=Path("/tmp/devcompanion-fix-evaluation.json"))
    a = ap.parse_args()

    binary = check.checker()
    if not binary:
        raise SystemExit("basedpyright not found (PATH, COMPANION_BASEDPYRIGHT or Mason)")
    cases = load(a.corpus)
    if a.only:
        cases = [c for c in cases if re.search(a.only, c.name)]
    started = time.monotonic()
    invalid = prepare(cases, binary)
    print(f"corpus: {len(cases)} cases, {len(invalid)} invalid ({time.monotonic() - started:.1f}s)")
    if a.check_corpus:
        for c in cases:
            codes = ", ".join(sorted({t["code"] or "syntax" for t in c.targets}))
            status = "INVALID " + "; ".join(invalid[c.name]) if c.name in invalid else codes
            print(f"  {c.name:26} {c.kind:22} {status}")
        raise SystemExit(1 if invalid else 0)

    if a.rejudge:
        result = json.loads(a.rejudge.read_text())
        by_name = {c.name: c for c in cases}
        for row in result["rows"]:
            row.update(judged(by_name[row["case"]], row["reply"], binary))
        result["rejudged_at"] = time.time()
        finish(result, a.rejudge)
        return

    if not a.model:
        raise SystemExit("--model is required unless --check-corpus or --rejudge")
    cases = [c for c in cases if c.name not in invalid]
    specs = [(text, providers.parse(text)) for text in a.model]
    if any(not s.remote for _, s in specs):
        installed = {m["name"] for m in call("/api/tags")["models"]}
        missing = [t for t, s in specs if not s.remote and s.model not in installed]
        if missing:
            raise SystemExit(f"not installed: {missing}; no automatic download or substitution")
    if a.append and a.output.exists():
        result = json.loads(a.output.read_text())
        if result["cases"] != len(cases):
            raise SystemExit(f"{a.output} holds {result['cases']} cases, the corpus now {len(cases)}")
    else:
        result = {"timestamp": time.time(), "checker": binary,
                  "corpus": str(a.corpus.relative_to(PROJECT)) if a.corpus.is_relative_to(PROJECT) else str(a.corpus),
                  "cases": len(cases), "invalid": invalid, "context_limit": 4096, "temperature": 0,
                  "models": {}, "rows": []}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    last_local = max((i for i, (_, s) in enumerate(specs) if not s.remote), default=-1)

    for i, (label, spec) in enumerate(specs):
        if label in result["models"]:
            print(f"{label}: already in {a.output}; remove it there to measure again")
            continue
        info = result["models"][label] = {"backend": spec.backend, "model": spec.model, "effort": spec.effort,
                                          "max_tokens": spec.tokens if not spec.remote else None,
                                          "measured_at": time.time()}
        keep = spec.keep_alive if i == last_local else "10m"
        if not spec.remote:
            spec = replace(spec, keep_alive=keep)
            t = time.monotonic()
            # Warm with the same placement the calls will ask for, or a CPU-only model loads on the
            # GPU first and evicts whatever holds the card.
            options = {"num_ctx": spec.ctx, **({"num_gpu": spec.gpu} if spec.gpu is not None else {})}
            call("/api/generate", {"model": spec.model, "prompt": "", "stream": False, "keep_alive": keep,
                                   "options": options}, timeout=300)
            info.update(load_s=round(time.monotonic() - t, 2), resident=call("/api/ps"),
                        ollama=call("/api/version"))
        print(f"\n{label}: {spec.backend}{' loaded in ' + str(info['load_s']) + 's' if 'load_s' in info else ''}", flush=True)
        jobs = a.jobs if spec.remote else 1
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            futures = [pool.submit(run_case, spec, label, c, binary) for c in cases]
            for future in futures:
                row = future.result()
                with lock:
                    result["rows"].append(row)
                    a.output.write_text(json.dumps(result, indent=2))
                print(f"  {row['case']:26} {row['outcome']:16} {row['form'] or '-':8} "
                      f"intent={'yes' if row['intent_ok'] else 'no ':3} {row['model_s']:6.2f}s "
                      f"{row['status'] if row['status'] != 'ok' else ''} {row['detail'][:50]}", flush=True)
        if not spec.remote and i != last_local:
            call("/api/generate", {"model": spec.model, "keep_alive": 0}, timeout=60)
    finish(result, a.output)


if __name__ == "__main__":
    main()
