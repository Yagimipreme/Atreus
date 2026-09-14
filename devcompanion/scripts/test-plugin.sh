#!/usr/bin/env bash
# Headless smoke test of the Neovim adapter. Proves, without an engine running:
#   1. autocmds fire and events land in inbox.jsonl with the contract's shape
#   2. diagnostics are captured through vim.diagnostic
#   3. findings.jsonl and engine.json written by anything are drawn in the panel
#   4. nothing opens or takes focus on its own
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
W="${1:-$(mktemp -d)}/ws"
rm -rf "$W"; mkdir -p "$W"; cd "$W"; git init -q .
cat > sample.py <<'PY'
def config_path():
    return "/tmp/x"
PY

cat > "$W/drive.lua" <<LUA
local W = "$W"
local companion = require("companion")
companion.setup({ debounce = { text = 50, diagnostics = 50, cursor = 50 } })
vim.cmd("edit " .. W .. "/sample.py")
companion.start(W)

-- simulate typing: change the buffer, which fires TextChanged
vim.api.nvim_buf_set_lines(0, 0, 1, false, { "def config_path(base):" })
vim.cmd("doautocmd TextChanged")

-- simulate a language server reporting an error, exactly as a real LSP would
local ns = vim.api.nvim_create_namespace("fake-lsp")
vim.diagnostic.set(ns, 0, { {
  lnum = 0, col = 4, end_lnum = 0, end_col = 15, severity = vim.diagnostic.severity.ERROR,
  message = "missing argument: base", code = "E0061", source = "fake-lsp",
} })

vim.cmd("write")
vim.wait(700, function() return false end)

-- an "engine" writes one finding
local f = io.open(W .. "/.companion/findings.jsonl", "w")
f:write(vim.json.encode({
  schema_version = 1, id = "f-1", kind = "caller_affected", surface = "errors",
  title = "config_path() gained a required parameter",
  basis = "observed", location = { path = "sample.py", line = 1, col = 5 },
  consequence = "Existing calls with no argument will raise TypeError",
  evidence = { { kind = "diagnostic", ref = "d-1", detail = "fake-lsp: missing argument: base" } },
  depends_on = { ["sample.py"] = "deadbeef" }, snapshot_id = "snap-1", created_ts = 1,
}) .. "\n")
f:close()
-- ...and reports itself alive, which is what the panel header renders
local st = io.open(W .. "/.companion/engine.json", "w")
st:write(vim.json.encode({
  schema_version = 1, pid = 4242, started_ts = 1, heartbeat_ts = os.time(), version = "0.2.0",
  state = "idle", workspace = W, session = vim.NIL, last_event_seq = 9, pending_tasks = 0,
  dirty_buffers = {}, revisions = vim.empty_dict(), findings = 1,
  model = { name = vim.NIL, backend = vim.NIL, status = "disabled" },
  context = { backend = "qmd", status = "disabled", passages = 0 }, last_error = vim.NIL,
}))
st:close()
vim.wait(2500, function()
  return require("companion.findings").count() > 0 and require("companion.panel").engine ~= nil
end)

local before = vim.api.nvim_get_current_win()
print("windows open before asking: " .. #vim.api.nvim_list_wins())
vim.cmd("CompanionPanel")
print("windows open after :CompanionPanel: " .. #vim.api.nvim_list_wins())
print("focus stayed in the code window: " .. tostring(vim.api.nvim_get_current_win() == before))
print("--- panel contents")
local buf = vim.fn.bufnr("companion://panel")
for _, l in ipairs(vim.api.nvim_buf_get_lines(buf, 0, -1, false)) do print(l) end
LUA

nvim --headless -u NONE --cmd "set rtp+=$HERE/nvim" \
  -c "runtime plugin/companion.lua" -c "luafile $W/drive.lua" -c "qa!" 2>&1

echo "--- inbox.jsonl (events the adapter emitted)"
python3 -c "
import json
for line in open('$W/.companion/inbox.jsonl'):
    e = json.loads(line)
    keep = {k: v for k, v in e.items() if k != 'text'}
    if 'text' in e: keep['text_len'] = len(e['text'])
    print(json.dumps(keep))
"
