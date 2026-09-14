-- Layer 3b: THE PANEL. One read-only side pane holding everything the engine currently knows,
-- instead of several scratch buffers that each hold a slice of it and disagree about when they
-- were last refreshed.
--
-- The pane is a view, never a source: it renders `findings.findings` (from findings.jsonl) and
-- `M.engine` (from engine.json) and owns no state of its own beyond the window. Refreshing it
-- while it is closed is free and is what keeps it correct the moment it is opened.
--
-- The vision's rule holds here above all: this window opens only when the developer asks.
local config = require("companion.config")
local util = require("companion.util")
local store = require("companion.findings")

local M = {}

-- Latest engine.json, or nil when no engine is running. Set by init.lua's watcher.
M.engine = nil

local state = { buf = nil, win = nil, root = nil }
local index = {}   -- line number -> finding, for <CR>

local BASIS_MARK = { observed = "*", inferred = "?", predicted = "~", outdated = "x" }
local SURFACE_TITLE = { callers = "CALLERS", errors = "ERRORS", docs = "DOCS", roadmap = "ROADMAP" }

local function ago(ts)
  if not ts then
    return "never"
  end
  local s = math.max(0, os.time() - math.floor(ts))
  return s < 90 and (s .. "s ago") or (math.floor(s / 60) .. "m ago")
end

-- ---------------------------------------------------------------- header fields

local function engine_line()
  local e = M.engine
  if not e then
    return "engine    not running"
  end
  local bits = { e.state or "?", "pid " .. tostring(e.pid), ago(e.heartbeat_ts),
                 (e.pending_tasks or 0) .. " pending", "seq " .. tostring(e.last_event_seq) }
  return "engine    " .. table.concat(bits, " · ")
end

-- The one question the developer actually has about this pane: is it talking about the code
-- I am looking at? Answered by comparing the buffer's canonical hash with the revision the
-- engine says it analysed, rather than by guessing from timestamps.
local function buffer_line(root)
  local buf = vim.api.nvim_get_current_buf()
  if state.buf and buf == state.buf then
    return nil                                   -- the pane itself is not a subject
  end
  local name = vim.api.nvim_buf_get_name(buf)
  if name == "" or vim.bo[buf].buftype ~= "" then
    return "buffer    (no file)"
  end
  local rel = util.relative(root, name)
  local sha = util.text_sha(util.canonical_text(buf))
  local rev = ((M.engine or {}).revisions or {})[rel]
  local sync
  if not rev then
    sync = M.engine and "not analysed yet" or "no engine"
  elseif rev.sha == sha then
    sync = rev.origin == "editor" and "analysed as unsaved buffer" or "analysed as saved file"
  else
    sync = "engine is behind this buffer"
  end
  return string.format("buffer    %s · %s · %s", rel,
    vim.bo[buf].modified and "unsaved" or "saved", sync)
end

local function model_line()
  local m = (M.engine or {}).model
  if not m then
    return "model     unknown"
  end
  return "model     " .. (m.status or "?") .. (m.name and (" · " .. m.name) or "")
    .. (m.backend and (" · " .. m.backend) or "")
end

local function context_line()
  local c = (M.engine or {}).context
  if not c then
    return "context   unknown"
  end
  return "context   " .. (c.backend or "?") .. " " .. (c.status or "?")
    .. " · " .. tostring(c.passages or 0) .. " passage(s)"
end

-- ---------------------------------------------------------------- findings

-- Stale means: this claim was derived from bytes that are no longer what the buffer holds.
-- Recomputed live here rather than trusted from the file, because the buffer moves on between
-- engine writes and a claim shown as current when it is not is the one failure that matters.
local function is_stale(root, finding)
  for rel, sha in pairs(finding.depends_on or {}) do
    local buf = vim.fn.bufnr(root .. "/" .. rel)
    if buf ~= -1 and vim.api.nvim_buf_is_loaded(buf) then
      if util.text_sha(util.canonical_text(buf)) ~= sha then
        return true
      end
    end
  end
  return false
end

local function finding_lines(finding, stale)
  local out = {}
  local mark = BASIS_MARK[finding.basis] or "*"
  -- Where the claim's own subject lives: "buffer" warns that the file on disk disagrees.
  local from = ""
  for _, origin in pairs(finding.revision or {}) do
    if origin == "editor" then
      from = "  [buffer]"
      break
    end
  end
  table.insert(out, string.format(" %s %s%s%s", mark, finding.title, from,
    stale and "  [stale]" or ""))
  local loc = finding.location
  if loc and loc.path then
    table.insert(out, string.format("     %s%s  %s", loc.path,
      loc.line and (":" .. loc.line) or "", finding.consequence or ""))
  elseif finding.consequence then
    table.insert(out, "     " .. finding.consequence)
  end
  for _, e in ipairs(finding.evidence or {}) do
    table.insert(out, string.format("     · %s: %s", e.kind, (e.detail or e.ref or ""):sub(1, 120)))
  end
  return out
end

-- ---------------------------------------------------------------- buffer plumbing

local function ensure_buffer()
  if state.buf and vim.api.nvim_buf_is_valid(state.buf) then
    return state.buf
  end
  local buf = vim.api.nvim_create_buf(false, true) -- unlisted, scratch, never written to disk
  vim.bo[buf].bufhidden = "hide"
  vim.bo[buf].filetype = "companion"
  vim.bo[buf].modifiable = false
  vim.api.nvim_buf_set_name(buf, "companion://panel")
  state.buf = buf
  return buf
end

-- nvim_buf_set_lines raises on a string containing a newline, which would take down the whole
-- pane. The engine flattens its fields, but this is a rendering boundary and it must hold
-- whatever it is handed: a pane that shows an awkward line is a nuisance, a pane that throws is
-- a broken tool. Belt and braces on purpose.
local function flatten(s)
  return (tostring(s):gsub("%s+", " "))
end

local function set_lines(buf, lines)
  for i, l in ipairs(lines) do
    if l:find("[\r\n]") then
      lines[i] = flatten(l)
    end
  end
  vim.bo[buf].modifiable = true
  vim.api.nvim_buf_set_lines(buf, 0, -1, false, lines)
  vim.bo[buf].modifiable = false
end

-- Rebuild the pane's contents. Safe and cheap to call when the pane is closed: the scratch
-- buffer is updated either way, so opening it later never shows a stale first frame.
-- `only` restricts the finding sections, which is all :CompanionErrors and :CompanionCallers are.
function M.refresh(root, only)
  root = root or state.root
  if not root then
    return
  end
  state.root = root
  local buf = ensure_buffer()
  index = {}

  local lines = { "companion · " .. vim.fn.fnamemodify(root, ":t"), "" }
  table.insert(lines, engine_line())
  local bl = buffer_line(root)
  if bl then
    table.insert(lines, bl)
  end
  table.insert(lines, model_line())
  table.insert(lines, context_line())
  local dirty = (M.engine or {}).dirty_buffers or {}
  if #dirty > 0 then
    table.insert(lines, "unsaved   " .. table.concat(dirty, ", "))
  end
  if (M.engine or {}).last_error then
    table.insert(lines, "last error " .. M.engine.last_error)
  end

  local shown, total = 0, 0
  for _, name in ipairs({ "callers", "errors", "docs", "roadmap" }) do
    local items = store.findings[name] or {}
    if #items > 0 and (only == nil or only == name) then
      total = total + #items
      table.insert(lines, "")
      table.insert(lines, SURFACE_TITLE[name] .. " (" .. #items .. ")")
      for _, f in ipairs(items) do
        if shown >= config.options.ui.max_findings then
          table.insert(lines, "     … " .. (#items - shown) .. " more")
          break
        end
        local stale = is_stale(root, f)
        if not (stale and config.options.ui.stale == "hide") then
          index[#lines + 1] = f
          vim.list_extend(lines, finding_lines(f, stale))
          shown = shown + 1
        end
      end
    end
  end
  if total == 0 then
    table.insert(lines, "")
    table.insert(lines, "nothing to report")
  end
  set_lines(buf, lines)
end

-- Open the pane. ONLY reached from a user command or keymap.
function M.open(root, only)
  local buf = ensure_buffer()
  M.refresh(root, only)
  if state.win and vim.api.nvim_win_is_valid(state.win) then
    vim.api.nvim_set_current_win(state.win)
    return
  end
  local previous = vim.api.nvim_get_current_win()
  vim.cmd(config.options.ui.split == "right" and "vsplit" or "split")
  local win = vim.api.nvim_get_current_win()
  vim.api.nvim_win_set_buf(win, buf)
  vim.api.nvim_win_set_width(win, config.options.ui.width)
  vim.wo[win].number = false
  vim.wo[win].relativenumber = false
  vim.wo[win].wrap = true
  vim.wo[win].signcolumn = "no"
  vim.wo[win].winfixwidth = true
  state.win = win

  vim.keymap.set("n", "<CR>", function() M.jump(root) end,
    { buffer = buf, desc = "companion: go to finding" })
  vim.keymap.set("n", "q", function() M.close() end,
    { buffer = buf, desc = "companion: close panel" })
  vim.keymap.set("n", "r", function() M.refresh(root) end,
    { buffer = buf, desc = "companion: refresh panel" })

  -- Opening is a request to see the pane, not to work in it: focus goes back where it was.
  if vim.api.nvim_win_is_valid(previous) then
    vim.api.nvim_set_current_win(previous)
  end
end

function M.close()
  if state.win and vim.api.nvim_win_is_valid(state.win) then
    vim.api.nvim_win_close(state.win, true)
  end
  state.win = nil
end

function M.is_open()
  return state.win ~= nil and vim.api.nvim_win_is_valid(state.win)
end

function M.toggle(root, only)
  if M.is_open() then
    M.close()
  else
    M.open(root, only)
  end
end

-- The finding whose block contains the cursor, then jump to it in the window we came from.
function M.jump(root)
  local cursor = vim.api.nvim_win_get_cursor(0)[1]
  local best, best_line = nil, 0
  for line, f in pairs(index) do
    if line <= cursor and line >= best_line then
      best, best_line = f, line
    end
  end
  if not best or not best.location or not best.location.path then
    return
  end
  vim.cmd("wincmd p")
  vim.cmd("edit " .. vim.fn.fnameescape(root .. "/" .. best.location.path))
  if best.location.line then
    vim.api.nvim_win_set_cursor(0, { best.location.line, math.max(0, (best.location.col or 1) - 1) })
  end
end

-- Called by init.lua whenever engine.json changes.
function M.set_engine(root, data)
  M.engine = data
  M.refresh(root)
end

return M
