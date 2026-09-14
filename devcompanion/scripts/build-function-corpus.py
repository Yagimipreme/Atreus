"""Build tests/fixtures/function-corpus.json: problems taken from this project's own committed
code, for scripts/evaluate-functions.py.

  .venv/bin/python scripts/build-function-corpus.py [--mutations 30] [--controls 10] [--sentences 30]

Everything is read from `git archive HEAD` -- the committed source, which is public -- extracted
into a scratch directory. The working tree is never read for content and never written.

  sentences  distinct basedpyright messages on that source for which present/problems.py has no
             rule, with the line they point at
  mutations  one planted bug in each of several functions of 10-60 lines: a flipped comparison or
             boolean operator, an off-by-one integer, a dropped `not`, a swapped True/False
             return. Kept only when the unit suite catches it and basedpyright reports no new
             error: a real bug the type checker cannot see. Each keeps the failing test's output
             and a packet for "which function is wrong": the functions the traceback passes
             through, and "functions changed since the last passing run" -- the culprit among
             other functions of similar size from the files involved, unmarked, shuffled.
  controls   functions left alone, so that "this looks fine" can be scored too.

The suite runs with bytecode writing off. A mutation that keeps the file's size, restored within
the same second, otherwise leaves its compiled module behind and breaks every later run -- which
is how a first build of this corpus produced 25 "bugs" that were all the same one.
"""
from __future__ import annotations

import argparse
import ast
import io
import json
import os
import random
import re
import subprocess
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from devcompanion.fix import check  # noqa: E402
from devcompanion.present.problems import flat, normalise  # noqa: E402

SEED = 20260914
FLIP = {ast.Lt: ("<", "<="), ast.LtE: ("<=", "<"), ast.Gt: (">", ">="), ast.GtE: (">=", ">"),
        ast.Eq: ("==", "!="), ast.NotEq: ("!=", "=="), ast.Is: ("is not", "is"),
        ast.IsNot: ("is not", "is"), ast.In: ("not in", "in"), ast.NotIn: ("not in", "in")}


@dataclass
class Site:
    line: int        # 1-based, in the file
    start: int       # character columns on that line
    end: int
    before: str
    after: str
    operator: str


def char_col(line: str, byte_col: int) -> int:
    """ast columns count UTF-8 bytes; the source has em dashes."""
    return len(line.encode("utf-8")[:byte_col].decode("utf-8", errors="ignore"))


def extract(dest: Path) -> tuple[Path, str]:
    top = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=PROJECT, capture_output=True,
                              text=True, check=True).stdout.strip())
    prefix = PROJECT.relative_to(top)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=top, capture_output=True,
                            text=True, check=True).stdout.strip()
    # nvim/ too: some tests start headless Neovim with the plugin.
    data = subprocess.run(["git", "archive", "HEAD", *(str(prefix / p) for p in ("src", "tests", "nvim", "pyproject.toml"))],
                          cwd=top, capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(dest, filter="data")
    return dest / prefix, commit


def pytest(base: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(base / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", "--tb=short", "tests"],
                          cwd=base, env=env, capture_output=True, text=True, timeout=300)


def sites(lines: list[str], fn: ast.FunctionDef) -> list[Site]:
    skip = {id(n) for js in ast.walk(fn) if isinstance(js, ast.JoinedStr) for n in ast.walk(js)}
    out = []
    for node in ast.walk(fn):
        if id(node) in skip or not hasattr(node, "lineno") or node.lineno != getattr(node, "end_lineno", None):
            continue
        text = lines[node.lineno - 1]
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in FLIP:
            a, b = char_col(text, node.left.end_col_offset), char_col(text, node.comparators[0].col_offset)
            token, swap = FLIP[type(node.ops[0])]
            if type(node.ops[0]) in (ast.Is, ast.In):
                token, swap = swap, token
            m = re.search(rf"(?<![<>=!\w]){re.escape(token)}(?![<>=\w])", text[a:b])
            if m:
                out.append(Site(node.lineno, a + m.start(), a + m.end(), token, swap, "comparison"))
        elif isinstance(node, ast.BoolOp) and len(node.values) == 2 and node.values[1].lineno == node.lineno:
            a, b = char_col(text, node.values[0].end_col_offset), char_col(text, node.values[1].col_offset)
            word = "and" if isinstance(node.op, ast.And) else "or"
            m = re.search(rf"\b{word}\b", text[a:b])
            if m:
                out.append(Site(node.lineno, a + m.start(), a + m.end(), word, "or" if word == "and" else "and", "boolean"))
        elif isinstance(node, ast.Constant) and type(node.value) is int:
            a, b = char_col(text, node.col_offset), char_col(text, node.end_col_offset)
            if text[a:b] == str(node.value):
                out.append(Site(node.lineno, a, b, str(node.value), str(node.value + 1), "off-by-one"))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            a, b = char_col(text, node.col_offset), char_col(text, node.operand.col_offset)
            if re.fullmatch(r"not\s+", text[a:b]):
                out.append(Site(node.lineno, a, b, text[a:b], "", "dropped not"))
        elif isinstance(node, ast.Return) and isinstance(node.value, ast.Constant) and type(node.value.value) is bool:
            a, b = char_col(text, node.value.col_offset), char_col(text, node.value.end_col_offset)
            out.append(Site(node.lineno, a, b, str(node.value.value), str(not node.value.value), "swapped bool"))
    return out


def defined(text: str) -> list[ast.FunctionDef]:
    return [n for n in ast.walk(ast.parse(text)) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def functions(base: Path) -> list[tuple[str, ast.FunctionDef]]:
    return [(str(path.relative_to(base)), node)
            for path in sorted((base / "src").rglob("*.py"))
            for node in defined(path.read_text()) if 10 <= node.end_lineno - node.lineno + 1 <= 60]


def span(fn: ast.FunctionDef) -> tuple[int, int]:
    return min([fn.lineno, *(d.lineno for d in fn.decorator_list)]), fn.end_lineno


def segment(text: str, start: int, end: int) -> str:
    return "\n".join(text.splitlines()[start - 1:end])


def enclosing(text: str, line: int) -> ast.FunctionDef | None:
    best = None
    for node in defined(text):
        if node.lineno <= line <= node.end_lineno and (best is None or node.lineno > best.lineno):
            best = node
    return best


def failure_of(output: str) -> tuple[list[str], str]:
    failed = re.findall(r"^(?:FAILED|ERROR) (\S+)", output, flags=re.M)
    body = output.split("= FAILURES =")[-1] if "= FAILURES =" in output else output
    body = body.split("short test summary info")[0]
    lines = [l for l in body.splitlines() if not set(l) <= set("=_ ")] or output.splitlines()
    if len(lines) > 80:
        lines = lines[:25] + ["[...]"] + lines[-55:]
    return failed, "\n".join(lines)


def entry(base: Path, rel: str, fn: ast.FunctionDef) -> dict:
    start, end = span(fn)
    return {"path": rel, "name": fn.name, "source": segment((base / rel).read_text(), start, end)}


def packet(base: Path, output: str, rel: str, culprit: ast.FunctionDef, rng: random.Random, changed: int = 6) -> dict:
    """What the companion would put in front of a model: the project functions the traceback passes
    through (at most four, the culprit left out of them), and `changed` recently changed
    functions -- the culprit among others of similar size from the files involved, shuffled."""
    trace: list[tuple[str, ast.FunctionDef]] = []
    files = [rel]
    for path, line in re.findall(r"^(\S+\.py):(\d+): in \w+", output, flags=re.M):
        full = Path(path) if Path(path).is_absolute() else base / path
        try:
            rel2 = str(full.resolve().relative_to(base.resolve()))
        except ValueError:
            continue
        fn = enclosing((base / rel2).read_text(), int(line))
        if fn is None or (rel2, fn.name) == (rel, culprit.name) or any((rel2, fn.name) == (r, f.name) for r, f in trace):
            continue
        if len(trace) < 4:
            trace.append((rel2, fn))
        if rel2.startswith("src/") and rel2 not in files:
            files.append(rel2)
    taken = {(r, f.name) for r, f in trace} | {(rel, culprit.name)}
    size = culprit.end_lineno - culprit.lineno
    pool = [(r, f) for r in files for f in defined((base / r).read_text())
            if (r, f.name) not in taken and 8 <= f.end_lineno - f.lineno <= max(40, 2 * size)]
    rng.shuffle(pool)
    recent = [(rel, culprit), *pool[:changed - 1]]
    rng.shuffle(recent)
    return {"trace": [entry(base, r, f) for r, f in trace], "changed": [entry(base, r, f) for r, f in recent]}


def harvest_sentences(base: Path, limit: int, binary: str) -> list[dict]:
    proc = subprocess.run([binary, "--outputjson", "src", "tests"], cwd=base, capture_output=True, text=True, timeout=300)
    seen, per_rule, out = set(), {}, []
    diags = json.loads(proc.stdout)["generalDiagnostics"]
    diags.sort(key=lambda d: (d["severity"] != "error", d.get("rule") or "", d["message"]))
    for d in diags:
        reading = normalise(d["message"])
        key = flat(d["message"])
        if reading.facts or reading.specificity or key in seen:
            continue
        rule = d.get("rule") or "syntax"
        if per_rule.get(rule, 0) >= 2:
            continue
        seen.add(key)
        per_rule[rule] = per_rule.get(rule, 0) + 1
        rel = str(Path(d["file"]).resolve().relative_to(base.resolve()))
        code = (base / rel).read_text().splitlines()[d["range"]["start"]["line"]]
        out.append({"id": f"sentence-{len(out) + 1:02d}", "rule": rule, "severity": d["severity"],
                    "message": d["message"], "code_line": code.strip(), "path": rel})
        if len(out) >= limit:
            break
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutations", type=int, default=30)
    ap.add_argument("--controls", type=int, default=10)
    ap.add_argument("--sentences", type=int, default=30)
    ap.add_argument("--output", type=Path, default=PROJECT / "tests/fixtures/function-corpus.json")
    a = ap.parse_args()
    binary = check.checker()
    if not binary:
        raise SystemExit("basedpyright not found")
    rng = random.Random(SEED)
    with tempfile.TemporaryDirectory(prefix="companion-corpus-") as tmp:
        base, commit = extract(Path(tmp))
        probe = subprocess.run([sys.executable, "-c", "import devcompanion; print(devcompanion.__file__)"],
                               cwd=base, env={**os.environ, "PYTHONPATH": str(base / "src")}, capture_output=True, text=True)
        if not probe.stdout.strip().startswith(str(base)):
            raise SystemExit(f"tests would import the wrong package: {probe.stdout.strip()}")
        started = time.monotonic()
        baseline = pytest(base)
        if baseline.returncode:
            raise SystemExit("the committed suite does not pass:\n" + baseline.stdout[-2000:])
        print(f"{commit}: suite passes in {time.monotonic() - started:.1f}s", flush=True)

        sentences = harvest_sentences(base, a.sentences, binary)
        print(f"sentences: {len(sentences)}", flush=True)

        candidates = functions(base)
        rng.shuffle(candidates)
        mutations, used, tried = [], set(), 0
        clean_errors: dict[str, list[dict]] = {}
        failing_tests: dict[str, int] = {}
        for rel, fn in candidates:
            if len(mutations) >= a.mutations:
                break
            path = base / rel
            original = path.read_text()
            lines = original.splitlines()
            options = sites(lines, fn)
            rng.shuffle(options)
            if rel not in clean_errors:
                clean_errors[rel] = [d for d in check.diagnose({rel: original}, binary)[rel] if d["severity"] == "error"]
            for site in options[:3]:
                tried += 1
                text = lines[site.line - 1]
                if text[site.start:site.end] != site.before:
                    continue
                changed = lines.copy()
                changed[site.line - 1] = text[:site.start] + site.after + text[site.end:]
                mutated = "\n".join(changed) + ("\n" if original.endswith("\n") else "")
                errors = [d for d in check.diagnose({rel: mutated}, binary)[rel] if d["severity"] == "error"]
                if check.introduced(clean_errors[rel], errors):
                    continue
                path.write_text(mutated)
                try:
                    run = pytest(base)
                    if run.returncode == 0:
                        continue
                    output = run.stdout + run.stderr
                    failed, failure = failure_of(output)
                    shown = packet(base, output, rel, fn, rng)
                finally:
                    path.write_text(original)
                if pytest(base).returncode:
                    raise SystemExit(f"restoring {rel} did not restore a passing suite")
                start, end = span(fn)
                for test in failed:
                    failing_tests[test] = failing_tests.get(test, 0) + 1
                mutations.append({
                    "id": f"mutation-{len(mutations) + 1:02d}", "path": rel, "function": fn.name,
                    "start": start, "end": end, "line": site.line, "line_in_function": site.line - start + 1,
                    "operator": site.operator, "before": site.before, "after": site.after,
                    "source": segment(original, start, end), "mutated_source": segment(mutated, start, end),
                    "failing_tests": failed, "failure": failure, "packet": shown, "in_packet": True})
                used.add((rel, fn.name))
                print(f"  {mutations[-1]['id']} {rel}::{fn.name} line {site.line} {site.operator} "
                      f"{site.before!r}->{site.after!r}; fails {failed[:1]}", flush=True)
                break
        controls = []
        for rel, fn in candidates:
            if len(controls) >= a.controls:
                break
            if (rel, fn.name) in used:
                continue
            start, end = span(fn)
            controls.append({"id": f"control-{len(controls) + 1:02d}", "path": rel, "function": fn.name,
                             "start": start, "end": end, "source": segment((base / rel).read_text(), start, end)})
        corpus = {"generated_at": time.time(), "source_commit": commit, "seed": SEED,
                  "mutations_tried": tried, "failing_tests": failing_tests,
                  "sentences": sentences, "mutations": mutations, "controls": controls}
    a.output.write_text(json.dumps(corpus, indent=2) + "\n")
    print(f"{len(mutations)} mutations from {tried} tried, {len(controls)} controls, {len(sentences)} sentences "
          f"-> {a.output}; distinct failing tests {len(failing_tests)}")


if __name__ == "__main__":
    main()
