"""Probe: does including passing call sites mislead the model?  A/B over identical evidence.

Usage:  uv run python scripts/probe-suggest.py <state-dir>
where <state-dir> is the --state of a run that produced a signature_change with a
breaking call site, e.g. from `companion replay examples/phase1-recording`.
"""
import json, sys
sys.path.insert(0, "src")
from devcompanion.llm.client import suggest

st = json.load(open(sys.argv[1] + "/state/state.json"))
rec = next(r for r in st.values() if r.get("title", "").startswith("add(a, b)"))

def payload(locs):
    return json.dumps({"change": rec["title"], "claim": rec["claim"],
                       "sites": [{"where": f"{l['path']}:{l['line']}", "verdict": l["verdict"],
                                  "why": l["reason"], "code": l["text"]} for l in locs][:12]})

ALL = rec["locations"]
BREAK = [l for l in ALL if l["verdict"] == "breaks"]
for model in ["qwen3:0.6b", "qwen2.5-coder:3b", "qwen3:4b"]:
    for label, locs in (("all-sites ", ALL), ("break-only", BREAK)):
        r = suggest(payload(locs), model=model)
        ok = r.text and "test_calc" in r.text
        print(f"{model:20} {label}  {r.status:4} {r.wall_s:5.2f}s tok={r.gen_tokens:<3} "
              f"{'HIT ' if ok else 'miss'} {(r.text or '')[:110]!r}")
