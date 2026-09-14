#!/usr/bin/env bash
# Replays the Phase 1 recording with a model attached; every record with a breaking call site
# triggers one suggestion call. Prints per-call wall time, tokens, and the sentence produced.
set -uo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
MODE="${1:-cpu}"; shift || true
MODELS=("${@:-qwen3:0.6b qwen2.5-coder:3b qwen3:4b qwen2.5:7b}")
[ "$MODE" = cpu ] && FLAG=--cpu-only || FLAG=
for m in ${MODELS[@]}; do
  ollama list | grep -q "^$m" || { echo "$m: not pulled -> unavailable case"; }
  ST=$(mktemp -d)
  echo "### $m ($MODE)"
  uv run --project "$HERE" companion --root "$ST/root" --state "$ST/state" --model "$m" $FLAG replay "$HERE/examples/phase1-recording" \
    | python3 -c '
import json,sys
lines=sys.stdin.read().splitlines(); d=json.loads(lines[-1])
for t in d["timings"]:
    if "llm" in t: print("  call:", json.dumps(t))
st=json.load(open(sys.argv[1]+"/state.json"))
for r in st.values():
    if r.get("suggestion"): print("  >", r["title"][:40], "=>", r["suggestion"])
' "$ST/state"
done
