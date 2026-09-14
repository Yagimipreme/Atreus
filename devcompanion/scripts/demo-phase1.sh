#!/usr/bin/env bash
# Phase 1 reproducible example: a signature change is detected, callers judged, tests run,
# board written. Produces a replayable recording in $OUT/.companion.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$(mktemp -d)}"
rm -rf "$OUT/fixture"; mkdir -p "$OUT"; cp -r "$HERE/examples/fixture" "$OUT/fixture"
cd "$OUT/fixture"; git init -q . && git add -A && git -c user.name=demo -c user.email=d@x commit -qm baseline
C=(uv run --project "$HERE" companion --root "$OUT/fixture")
echo "== 1. baseline observation (first sight of each file -> noop)"
"${C[@]}" ingest calc.py report.py tests/test_calc.py
echo "== 2. developer adds a required parameter to add() and renames memo -> note"
sed -i 's/^def add(a, b):/def add(a, b, carry):/; s/def post(self, amount, memo):/def post(self, amount, note):/' calc.py
"${C[@]}" ingest calc.py
echo "== 3. mid-edit save that does not parse -> unknown_intent, no false claims"
printf 'def scale(values, factor=1\n    return values\n' > calc_broken.py
"${C[@]}" ingest calc_broken.py
echo "== 4. developer fixes one caller -> evidence for report.py goes stale, then re-judged"
sed -i 's/t = add(t, x)/t = add(t, x, 0)/' report.py
"${C[@]}" ingest report.py
echo; echo "== BOARD"; cat .companion/board.md; echo "== QUICKFIX"; cat .companion/quickfix.txt
echo "recording: $OUT/fixture/.companion  (events.jsonl + snapshots/ = replayable input)"
