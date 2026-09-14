#!/usr/bin/env bash
# Live mode: `companion watch` runs in the background; a headless Neovim with the plugin loaded
# edits a signature and saves. Both the inotify producer and the Neovim producer fire; the engine
# de-duplicates by content sha, so one investigation runs.
set -uo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"; D="$1"
rm -rf "$D"; cp -r "$HERE/examples/fixture" "$D"; (cd "$D" && git init -q . && git add -A && git -c user.name=demo -c user.email=d@x commit -qm baseline)
uv run --project "$HERE" companion --root "$D" watch > "$D/.watch.log" 2>&1 & W=$!
sleep 2
nvim --headless -u NONE --cmd "set rtp+=$HERE/nvim" -c "runtime plugin/companion.lua" \
  -c "edit $D/calc.py" -c '%s/def add(a, b):/def add(a, b, carry):/' -c write -c 'qa!' 2>&1
T0=$(date +%s.%N)
for i in $(seq 1 100); do grep -q "signature_change" "$D/.companion/board.md" 2>/dev/null && break; sleep 0.1; done
T1=$(date +%s.%N)
echo "board updated $(python3 -c "print(round($T1-$T0,2))")s after save"
kill $W 2>/dev/null
echo "== events (source column)"; python3 -c "
import json,sys
for l in open('$D/.companion/events.jsonl'): e=json.loads(l); print(' ', e['seq'], e['source'], e['kind'], e['path'], (e['content_sha'] or '')[:8], e.get('line'))"
echo "== watch log"; cat "$D/.watch.log"
echo "== board (head)"; sed -n '1,12p' "$D/.companion/board.md"
