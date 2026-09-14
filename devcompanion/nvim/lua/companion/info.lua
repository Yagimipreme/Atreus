-- :CompanionInfo. What the developer of the companion needs and someone coding does not: the
-- engine process, whether it has read this buffer, the model, retrieval, intake counters, the
-- adapter's own. It used to be the header of the panel, which is what made the panel read like
-- a log.
local util = require("companion.util")
local store = require("companion.findings")
local float = require("companion.float")

local M = {}

local state = { buf = nil, win = nil }

local LABEL = 10

local function ago(ts)
  if not ts then
    return "never"
  end
  local s = math.max(0, os.time() - math.floor(ts))
  return s < 90 and (s .. "s ago") or (math.floor(s / 60) .. "m ago")
end

local function joined(...)
  local out = {}
  for i = 1, select("#", ...) do
    local v = select(i, ...)
    if v ~= nil and v ~= "" then
      table.insert(out, tostring(v))
    end
  end
  return table.concat(out, " · ")
end

-- { label, value, highlight? } rows. `adapter` is { observing, seq, session } from init.lua.
local function rows(root, buf, adapter)
  local e = store.engine
  local alive = store.engine_alive()
  local out = {}
  local function row(label, value, group)
    table.insert(out, { label, value, group })
  end

  if e then
    row("engine", joined(alive and (e.state or "?") or "stopped", "pid " .. tostring(e.pid),
      "heartbeat " .. ago(e.heartbeat_ts), (e.pending_tasks or 0) .. " pending",
      "seq " .. tostring(e.last_event_seq)), not alive and "CompanionWarn" or nil)
    row("version", joined(e.version, "started " .. ago(e.started_ts), e.session and ("following " .. e.session)))
  else
    row("engine", "not running · no engine.json under .companion/", "CompanionWarn")
  end

  -- Is this talking about the code in front of me? Compared by canonical hash, not by time.
  local name = vim.api.nvim_buf_get_name(buf)
  if name == "" or vim.bo[buf].buftype ~= "" then
    row("buffer", "(no file)")
  else
    local rel = util.relative(root, name)
    local sync = store.sync(root, buf)
    local origin = (((e or {}).revisions or {})[rel] or {}).origin
    local said = (sync == "current" and (origin == "editor" and "analysed as unsaved buffer"
                                                             or "analysed as saved file"))
      or (sync == "behind" and "engine is behind this buffer")
      or (e and "not in the analysis manifest" or "no engine")
    row("buffer", joined(rel, vim.bo[buf].modified and "unsaved" or "saved", said))
  end

  local dirty = (e or {}).dirty_buffers or {}
  row("unsaved", #dirty > 0 and table.concat(dirty, ", ") or "none")

  local m = (e or {}).model or {}
  row("model", joined(m.status or "unknown", m.name, m.backend))
  local ctx = (e or {}).context or {}
  row("context", joined((ctx.backend or "?") .. " " .. (ctx.status or "unknown"),
    tostring(ctx.passages or 0) .. " passage(s)"))
  local intake = (e or {}).intake
  if intake then
    row("intake", joined("offset " .. tostring(intake.offset or 0),
      "resumed at " .. tostring(intake.resumed_at or 0), (intake.skipped_known or 0) .. " skipped",
      (intake.malformed or 0) .. " malformed", (intake.resets or 0) .. " resets"))
  end

  row("adapter", joined(adapter.observing and "observing" or "not observing",
    adapter.seq .. " events sent", "session " .. adapter.session))
  local counts = {}
  for _, surface in ipairs(store.SURFACES) do
    local n = #(store.findings[surface] or {})
    if n > 0 then
      table.insert(counts, surface .. " " .. n)
    end
  end
  row("findings", #counts > 0 and table.concat(counts, " · ") or "none published")
  for _, f in ipairs(store.findings.errors or {}) do
    if f.kind == "test_result" then
      row("tests", joined(f.consequence, f.title, store.is_stale(root, f) and "stale"))
    end
  end
  if e and e.last_error then
    row("error", e.last_error, "CompanionError")
  end
  return out
end

function M.close()
  local win = state.win
  state.win = nil
  if win and vim.api.nvim_win_is_valid(win) then
    vim.api.nvim_win_close(win, true)
  end
end

-- Open the info view, centred. ONLY reached from a user command or keymap.
function M.open(root, adapter)
  local buf = vim.api.nvim_get_current_buf()
  M.close()
  if not (state.buf and vim.api.nvim_buf_is_valid(state.buf)) then
    state.buf = float.scratch("companion://info")
    for _, lhs in ipairs({ "q", "<Esc>" }) do
      vim.keymap.set("n", lhs, M.close, { buffer = state.buf, nowait = true, desc = "companion: close" })
    end
    vim.api.nvim_create_autocmd("WinLeave", {
      buffer = state.buf,
      callback = function()
        vim.schedule(M.close)
      end,
    })
  end

  local width = math.max(40, math.min(88, vim.o.columns - 6))
  local c = float.canvas()
  for _, r in ipairs(rows(root, buf, adapter)) do
    local lines = float.wrap(r[2], width - LABEL - 3)
    for i, l in ipairs(#lines > 0 and lines or { "" }) do
      c:add({ { " " }, { i == 1 and string.format("%-" .. LABEL .. "s", r[1]) or string.rep(" ", LABEL),
        "CompanionMuted" }, { " " }, { l, r[3] } })
    end
  end
  float.draw(state.buf, c)

  local height = math.max(1, math.min(#c.lines, vim.o.lines - 6))
  state.win = float.open(state.buf, {
    relative = "editor",
    row = math.max(0, math.floor((vim.o.lines - height) / 2) - 1),
    col = math.max(0, math.floor((vim.o.columns - width) / 2)),
    width = width,
    height = height,
    title = { { " companion info ", "CompanionTitle" } },
    title_pos = "left",
    footer = { { " q", "CompanionKey" }, { " close ", "CompanionMuted" } },
    footer_pos = "right",
  })
  vim.wo[state.win].cursorline = false
end

return M
