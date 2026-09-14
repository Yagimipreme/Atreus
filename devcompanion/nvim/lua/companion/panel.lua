-- Layer 3b: THE PANEL. The companion's quick-help surface: a small float at the right edge of
-- the editor holding a short, prioritised list of problems.
--
-- One line per problem, one inspected problem at a time, raw evidence only on request. The
-- engine has already grouped the language server's messages into problems and said each as a
-- sentence with its facts named (present/problems.py); this module lays that out and spends
-- colour only where the eye should go: the symbol, what was expected, what was there instead.
--
-- It is a view, never a source: it renders the findings store and owns only its window, which
-- problem is inspected, and where the cursor is. Engine metadata is not here; see info.lua.
--
-- It opens only when the developer asks. Having been asked, it takes focus -- its keys act
-- inside it -- and it closes on q, a jump, or leaving it, handing the cursor back to the window
-- it was opened from. Sticky (`ui.sticky`, :CompanionPanelStick, `s`) keeps it open on leaving
-- and after a jump, for when it should stay in view while coding.
local config = require("companion.config")
local store = require("companion.findings")
local float = require("companion.float")

local M = {}

local state = { buf = nil, win = nil, root = nil, origin = nil, only = nil, sticky = nil }
local open = { id = nil, raw = false } -- the one inspected problem, and whether its raw evidence shows
local items = {}                        -- as drawn: { first = lnum, last = lnum, finding = f }
local footer_key = nil                  -- the footer last applied; cursor moves redraw it only on change
local selection = vim.api.nvim_create_namespace("companion.selection")

-- " ▸ E  " -- marker, letter, then the place and the sentence from this column.
local INDENT = 6
local PAD = string.rep(" ", INDENT)
local LABEL = 11 -- "diagnostic" and a space
local LETTER = { test_result = "T", caller_affected = "C", diagnostic_context = "E" }
local FACT_HL = { symbol = "CompanionSymbol", expected = "CompanionExpected", got = "CompanionGot" }
local SKIP_CAPTURE = { spell = true, nospell = true, conceal = true }

function M.is_open()
  return state.win ~= nil and vim.api.nvim_win_is_valid(state.win)
end

-- The workspace the panel was last opened for, or nil.
function M.root()
  return state.root
end

local function focused()
  return M.is_open() and vim.api.nvim_get_current_win() == state.win
end

-- The session's choice when one was made, otherwise the configured default.
function M.is_sticky()
  if state.sticky ~= nil then
    return state.sticky
  end
  return config.options.ui.sticky == true
end

local function inner_width()
  return math.max(30, math.min(config.options.ui.width, vim.o.columns - 4))
end

-- The buffer the developer is looking at: the current one, unless that is the panel itself.
local function subject_buf()
  if focused() and state.origin and vim.api.nvim_win_is_valid(state.origin) then
    return vim.api.nvim_win_get_buf(state.origin)
  end
  return vim.api.nvim_get_current_buf()
end

-- ---------------------------------------------------------------- what a finding says

local function unsaved(f)
  for _, origin in pairs(f.revision or {}) do
    if origin == "editor" then
      return true
    end
  end
  return false
end

local function place(f)
  local loc = f.location
  if loc and loc.path then
    return vim.fn.fnamemodify(loc.path, ":t") .. (loc.line and (":" .. loc.line) or "")
  end
  return f.title or f.kind or "?"
end

-- The one sentence. A diagnostic's title is the engine's reading of the language server; for a
-- call site or a test run the consequence says what happens, and the title what changed.
local function sentence(f)
  if f.kind ~= "diagnostic_context" and f.consequence and f.consequence ~= "" then
    return f.consequence
  end
  return f.title or ""
end

-- Where a jump goes: the finding's own place, or for a test run the first test file it ran.
local function target(f)
  if f.location and f.location.path then
    return f.location
  end
  for _, path in ipairs(f.scope or {}) do
    if path:match("test") then
      return { path = path }
    end
  end
end

-- The line a finding points at, as it is now, without its indent, and the caret's display
-- offset into it. nil when there is no line to show.
local function excerpt(root, loc)
  if not (loc and loc.path and loc.line) then
    return nil
  end
  local abs = root .. "/" .. loc.path
  local text
  local buf = vim.fn.bufnr(abs)
  if buf ~= -1 and vim.api.nvim_buf_is_loaded(buf) then
    text = vim.api.nvim_buf_get_lines(buf, loc.line - 1, loc.line, false)[1]
  elseif vim.fn.filereadable(abs) == 1 then
    text = vim.fn.readfile(abs, "", loc.line)[loc.line]
  end
  if not text or not text:find("%S") then
    return nil
  end
  local indent = #text:match("^%s*")
  local body = text:sub(indent + 1)
  local caret = loc.col and float.width(body:sub(1, math.max(0, loc.col - 1 - indent))) or nil
  return body, caret
end

-- ---------------------------------------------------------------- rows

-- Byte spans of the facts inside a sentence, in order. `got` is taken at its last occurrence,
-- because sentences end with it; the others at their first.
local function fact_spans(text, facts)
  local spans = {}
  for key, group in pairs(FACT_HL) do
    local value = type(facts) == "table" and facts[key] or nil
    if type(value) == "string" and value ~= "" then
      local s, e = text:find(value, 1, true)
      while key == "got" and s do
        local s2, e2 = text:find(value, s + 1, true)
        if not s2 then
          break
        end
        s, e = s2, e2
      end
      if s then
        table.insert(spans, { s, e, group })
      end
    end
  end
  table.sort(spans, function(a, b) return a[1] < b[1] end)
  return spans
end

-- The sentence, wrapped rather than cut, with each fact in its own colour. Everything else in
-- it stays plain: a sentence that is all red tells the eye nothing.
local function sentence_rows(c, text, facts, width, dim)
  local spans = fact_spans(text, facts)
  local offset = 0
  for _, l in ipairs(float.wrap(text, width - INDENT - 1)) do
    local start = text:find(l, offset + 1, true) or (offset + 1)
    local stop = start + #l - 1
    local parts, pos = { { PAD } }, start
    for _, sp in ipairs(spans) do
      local s, e = math.max(sp[1], start), math.min(sp[2], stop)
      if s <= e and s >= pos then
        if s > pos then
          table.insert(parts, { text:sub(pos, s - 1), dim })
        end
        table.insert(parts, { text:sub(s, e), dim or sp[3] })
        pos = e + 1
      end
    end
    if pos <= stop then
      table.insert(parts, { text:sub(pos, stop), dim })
    end
    c:add(parts)
    offset = stop
  end
end

-- The line of code, highlighted by Tree-sitter when a parser for it is installed, and a caret
-- under the column the problem is at. Returns whether there was a line to show.
local function code_rows(c, root, loc, width)
  local body, caret = excerpt(root, loc)
  if not body then
    return false
  end
  local room = width - INDENT - 1
  local shown = float.truncate(body, room)
  local row = c:add({ { PAD }, { shown } })
  local ft = vim.filetype.match({ filename = loc.path })
  local lang = ft and vim.treesitter.language.get_lang(ft)
  if lang then
    pcall(function()
      local tree = vim.treesitter.get_string_parser(shown, lang):parse()[1]
      local query = vim.treesitter.query.get(lang, "highlights")
      if not (tree and query) then
        return
      end
      for id, node in query:iter_captures(tree:root(), shown, 0, 1) do
        local name = query.captures[id]
        local sr, sc, er, ec = node:range()
        if sr == 0 and not SKIP_CAPTURE[name] and name:sub(1, 1) ~= "_" then
          c:mark(row, INDENT + sc, INDENT + (er == 0 and ec or #shown), "@" .. name .. "." .. lang)
        end
      end
    end)
  end
  if caret and caret < room then
    c:add({ { PAD .. string.rep(" ", caret) }, { "^", "CompanionGot" } })
  end
  return true
end

-- A labelled value, wrapped under its own column.
local function kv(c, label, value, group, width)
  local lines = float.wrap(value, width - INDENT - LABEL - 1)
  for i, l in ipairs(#lines > 0 and lines or { "" }) do
    c:add({ { PAD }, { i == 1 and string.format("%-" .. LABEL .. "s", label) or string.rep(" ", LABEL),
      "CompanionMuted" }, { l, group } })
  end
end

-- `d`: where the claim came from. Kept out of the inspected view because it answers "can I
-- trust this?", which is a different question from "what is wrong?".
local function raw_rows(c, f, stale, width)
  local source = (f.kind == "test_result" and "pytest")
    or (f.kind == "caller_affected" and "call-site check")
    or (f.consequence or ""):match("^(%S+)") or "language server"
  kv(c, "source", source, "CompanionMuted", width)
  for _, e in ipairs(f.evidence or {}) do
    if e.kind == "diagnostic" then
      kv(c, "diagnostic", ((e.ref and e.ref ~= "-") and (e.ref .. ": ") or "") .. (e.detail or ""),
        "CompanionMuted", width)
    elseif e.kind == "snapshot" and e.detail then
      kv(c, "call", e.detail, "CompanionMuted", width)
    end
  end
  kv(c, "basis", stale and "stale, the code changed since" or (f.basis or "observed"), "CompanionMuted", width)
  if f.kind == "test_result" then
    kv(c, "revision", "saved files only", "CompanionMuted", width)
  else
    kv(c, "buffer", unsaved(f) and "unsaved" or "saved", "CompanionMuted", width)
  end
end

-- ↵: the problem, not its paperwork. The code, the mismatch, what changed, a likely fix when a
-- model offered one.
local function inspected(c, root, f, stale, width)
  c:gap()
  if code_rows(c, root, f.location, width) then
    c:gap()
  end
  local facts = f.facts or {}
  if facts.got or facts.expected then
    if facts.got then
      kv(c, "got", facts.got, "CompanionGot", width)
    end
    if facts.expected then
      kv(c, "expected", facts.expected, "CompanionExpected", width)
    end
    if facts.parameter then
      kv(c, "parameter", facts.parameter, nil, width)
    end
    c:gap()
  end
  if f.kind == "caller_affected" and f.title and f.title ~= "" then
    kv(c, "change", f.title, nil, width)
    c:gap()
  elseif f.kind == "test_result" then
    for _, e in ipairs(f.evidence or {}) do
      if e.kind == "test" and e.detail then
        local label = e.detail:match("^FAILED") and "failed" or (e.detail:match("^E%s") and "error" or "output")
        kv(c, label, e.detail, nil, width)
      end
    end
    c:gap()
  end
  for _, e in ipairs(f.evidence or {}) do
    if e.kind == "model" and e.detail then
      c:add({ { PAD }, { "likely fix", "CompanionKey" } })
      for _, l in ipairs(float.wrap(e.detail, width - INDENT - 1)) do
        c:add({ { PAD }, { l } })
      end
      c:gap()
    end
  end
  if open.raw then
    raw_rows(c, f, stale, width)
  end
end

local function item(c, root, entry, width)
  local f, stale = entry.finding, entry.stale
  local dim = stale and "CompanionMuted" or nil
  local inferred = f.basis == "inferred"
  local is_open = open.id == f.id
  local tag = stale and "stale" or (unsaved(f) and "unsaved" or nil)
  local where = float.truncate(place(f), width - INDENT - 1 - (tag and float.width(tag) + 2 or 0))
  local row = {
    { " " },
    { is_open and "▼" or " ", "CompanionKey" },
    { " " },
    { inferred and "?" or (LETTER[f.kind] or "•"), dim or (inferred and "CompanionWarn" or "CompanionError") },
    { "  " },
    { where, dim or "CompanionLocation" },
  }
  if tag then
    table.insert(row, { string.rep(" ", math.max(2, width - INDENT - float.width(where) - float.width(tag) - 1)) })
    table.insert(row, { tag, "CompanionMuted" })
  end
  local first = c:add(row)
  sentence_rows(c, sentence(f), f.facts, width, dim)
  if is_open then
    inspected(c, root, f, stale, width)
  end
  return first
end

-- ---------------------------------------------------------------- the whole panel

local function render()
  local root, width = state.root, inner_width()
  local c = float.canvas()
  items = {}

  -- An unobserved workspace has no problems list to show, not an empty one: "no problems" and an
  -- engine notice would both describe what nobody read.
  if not store.observing(root) then
    c:add({ { " " }, { "not observing this workspace", "CompanionWarn" } })
    c:add({ { " " }, { ":CompanionStart", "CompanionKey" }, { " to begin", "CompanionMuted" } })
    float.draw(state.buf, c)
    return #c.lines
  end

  local list = store.issues(root, state.only)

  local still_there, diag_problems, diag_messages = false, 0, 0
  for _, entry in ipairs(list) do
    still_there = still_there or entry.finding.id == open.id
    if entry.finding.kind == "diagnostic_context" then
      diag_problems = diag_problems + 1
      diag_messages = diag_messages + (tonumber(entry.finding.diagnostics) or 1)
    end
  end
  if not still_there then
    open.id, open.raw = nil, false
  end

  -- Problems, not messages. When grouping absorbed some, say how many machine messages the
  -- count stands for: that difference is the point of the panel.
  local n = #list
  local count = n == 0 and "no problems" or (n == 1 and "1 problem" or (n .. " problems"))
  local detail = diag_messages > diag_problems and (" · " .. diag_messages .. " diagnostics") or ""
  if state.only then
    detail = detail .. " · " .. state.only
  end
  local tests, right, right_hl = store.tests(root), "", nil
  if tests and state.only ~= "callers" then
    if tests.passed > 0 then
      right, right_hl = "✓ " .. tests.passed .. " tests", tests.stale and "CompanionMuted" or "CompanionOk"
    elseif tests.other then
      right, right_hl = "tests " .. tests.other, "CompanionMuted"
    end
  end
  local used = 1 + float.width(count) + float.width(detail)
  if right ~= "" and used + 2 + float.width(right) > width then
    right = (right:gsub(" tests$", ""))
  end
  c:add({
    { " " },
    { count, n == 0 and "CompanionOk" or "CompanionTitle" },
    { detail, "CompanionMuted" },
    { string.rep(" ", math.max(1, width - used - float.width(right) - 1)) },
    { right, right_hl },
  })

  -- One line about the engine, and only when it changes what the list means.
  local notice, notice_hl
  if not store.engine_alive() then
    notice = store.engine and "engine stopped · showing its last results" or "engine not running"
    notice_hl = "CompanionWarn"
  elseif store.engine.last_error then
    notice, notice_hl = "engine error · :CompanionInfo", "CompanionError"
  elseif store.busy(root, subject_buf()) then
    notice, notice_hl = "analysing…", "CompanionMuted"
  end
  if notice then
    c:add({ { " " }, { float.truncate(notice, width - 2), notice_hl } })
  end

  local max = config.options.ui.max_findings
  for i, entry in ipairs(list) do
    c:gap()
    if i > max then
      c:add({ { PAD }, { "… " .. (#list - max) .. " more", "CompanionMuted" } })
      break
    end
    local first = item(c, root, entry, width)
    c:trim()
    table.insert(items, { first = first, last = #c.lines, finding = entry.finding })
  end

  float.draw(state.buf, c)
  return #c.lines
end

local function title()
  local chunks = { { " companion ", "CompanionTitle" } }
  if M.is_sticky() then
    table.insert(chunks, { "· sticky ", "CompanionMuted" })
  end
  return chunks
end

local function item_at(lnum)
  local found
  for _, it in ipairs(items) do
    if it.first > lnum then
      break
    end
    found = it
  end
  return found
end

-- The keys that do something where the cursor is. Only keys that exist: no `f fix` until the
-- engine can propose one.
local function footer()
  local cur = M.is_open() and item_at(vim.api.nvim_win_get_cursor(state.win)[1]) or nil
  local keys
  if #items == 0 then
    keys = { { "q", "close" } }
  elseif cur and cur.finding.id == open.id then
    keys = { { "↵", "go to" }, { "d", open.raw and "hide raw" or "raw" }, { "q", "close" } }
  else
    keys = { { "↵", "inspect" }, { "s", M.is_sticky() and "unstick" or "stick" }, { "q", "close" } }
  end
  local chunks = {}
  for _, k in ipairs(keys) do
    table.insert(chunks, { " " .. k[1], "CompanionKey" })
    table.insert(chunks, { " " .. k[2] .. " ", "CompanionMuted" })
  end
  return chunks
end

-- Size and place the window around `height` lines, opening it if it is not open.
local function place_window(height)
  local keys = footer()
  footer_key = vim.inspect(keys)
  local cfg = {
    relative = "editor",
    anchor = "NE",
    row = 1,
    col = vim.o.columns - 1,
    width = inner_width(),
    height = math.max(1, math.min(height, vim.o.lines - vim.o.cmdheight - 4)),
    title = title(),
    title_pos = "left",
    footer = keys,
    footer_pos = "right",
  }
  if M.is_open() then
    vim.api.nvim_win_set_config(state.win, cfg)
  else
    state.win = float.open(state.buf, cfg)
  end
end

-- The selection marker and the footer follow the cursor, without a redraw of the list.
local function mark_selection()
  if not M.is_open() then
    return
  end
  vim.api.nvim_buf_clear_namespace(state.buf, selection, 0, -1)
  local cur = item_at(vim.api.nvim_win_get_cursor(state.win)[1])
  if cur then
    vim.api.nvim_buf_set_extmark(state.buf, selection, cur.first - 1, 1, {
      virt_text = { { cur.finding.id == open.id and "▼" or "▸", "CompanionKey" } },
      virt_text_pos = "overlay",
    })
  end
  local keys = footer()
  local key = vim.inspect(keys)
  if key ~= footer_key then
    footer_key = key
    vim.api.nvim_win_set_config(state.win, { footer = keys, footer_pos = "right" })
  end
end

-- Put the cursor on a problem's first row, and scroll so as much of it as fits is in view.
local function show_item(id)
  for _, it in ipairs(items) do
    if it.finding.id == id then
      vim.api.nvim_win_set_cursor(state.win, { it.first, 0 })
      vim.api.nvim_win_call(state.win, function()
        local height = vim.api.nvim_win_get_height(0)
        if it.last > vim.fn.line("w0") + height - 1 then
          vim.fn.winrestview({ topline = math.max(1, math.min(it.first, it.last - height + 1)) })
        end
      end)
    end
  end
  mark_selection()
end

-- ---------------------------------------------------------------- actions

-- Redraw in place, keeping the cursor where it was within the problem it was on. Free while the
-- panel is closed: opening rebuilds from the store, so there is nothing to keep current.
function M.refresh(root)
  state.root = root or state.root
  if not M.is_open() or not state.root then
    return
  end
  local lnum = vim.api.nvim_win_get_cursor(state.win)[1]
  local was = item_at(lnum)
  local id, offset = was and was.finding.id, was and (lnum - was.first) or 0
  place_window(render())
  local line = lnum
  for _, it in ipairs(items) do
    if id and it.finding.id == id then
      line = math.min(it.first + offset, it.last)
      break
    end
  end
  vim.api.nvim_win_set_cursor(state.win,
    { math.max(1, math.min(line, vim.api.nvim_buf_line_count(state.buf))), 0 })
  mark_selection()
end

function M.close()
  local win = state.win
  state.win = nil
  if not (win and vim.api.nvim_win_is_valid(win)) then
    return
  end
  local was_current = vim.api.nvim_get_current_win() == win
  vim.api.nvim_win_close(win, true)
  -- Only when the panel had the cursor: a developer who clicked into another window chose it.
  if was_current and state.origin and vim.api.nvim_win_is_valid(state.origin) then
    vim.api.nvim_set_current_win(state.origin)
  end
end

function M.jump()
  local it = item_at(vim.api.nvim_win_get_cursor(0)[1])
  local loc = it and target(it.finding)
  if not loc then
    return
  end
  local root = state.root
  if not M.is_sticky() then
    M.close()
  elseif state.origin and vim.api.nvim_win_is_valid(state.origin) and state.origin ~= state.win then
    vim.api.nvim_set_current_win(state.origin)
  else
    vim.cmd("wincmd p")
  end
  -- :drop goes to a window already showing the file, and splits rather than failing when the
  -- current buffer has unsaved changes.
  vim.cmd("drop " .. vim.fn.fnameescape(root .. "/" .. loc.path))
  if loc.line then
    pcall(vim.api.nvim_win_set_cursor, 0, { loc.line, math.max(0, (loc.col or 1) - 1) })
  end
end

-- ↵: inspect this problem, putting away whichever was open; on the inspected one, go to it.
function M.inspect()
  local it = item_at(vim.api.nvim_win_get_cursor(0)[1])
  if not it then
    return
  end
  if open.id == it.finding.id then
    return M.jump()
  end
  open.id, open.raw = it.finding.id, false
  M.refresh()
  show_item(it.finding.id)
end

-- d: the raw evidence, inspecting the problem first if it was not.
function M.toggle_raw()
  local it = item_at(vim.api.nvim_win_get_cursor(0)[1])
  if not it then
    return
  end
  if open.id == it.finding.id then
    open.raw = not open.raw
  else
    open.id, open.raw = it.finding.id, true
  end
  M.refresh()
  show_item(it.finding.id)
end

-- <Esc>: put the inspected problem away; with none open, close.
function M.escape()
  if not open.id then
    return M.close()
  end
  local id = open.id
  open.id, open.raw = nil, false
  M.refresh()
  show_item(id)
end

-- Move by problem rather than by line: a problem is two lines, or many while inspected.
function M.step(delta)
  if #items == 0 then
    return
  end
  local cur = item_at(vim.api.nvim_win_get_cursor(0)[1])
  local index = 0
  for i, it in ipairs(items) do
    if it == cur then
      index = i
    end
  end
  local next_index = cur and math.max(1, math.min(#items, index + delta)) or 1
  vim.api.nvim_win_set_cursor(0, { items[next_index].first, 0 })
  mark_selection()
end

local function ensure_buffer()
  if state.buf and vim.api.nvim_buf_is_valid(state.buf) then
    return state.buf
  end
  local buf = float.scratch("companion://panel")
  state.buf = buf
  local function map(lhs, fn, desc)
    vim.keymap.set("n", lhs, fn, { buffer = buf, nowait = true, desc = "companion: " .. desc })
  end
  map("<CR>", M.inspect, "inspect, or go to the inspected problem")
  map("d", M.toggle_raw, "raw evidence")
  map("j", function() M.step(1) end, "next problem")
  map("k", function() M.step(-1) end, "previous problem")
  map("s", function() M.set_sticky() end, "stick or unstick")
  map("r", function() M.refresh() end, "redraw")
  map("q", M.close, "close")
  map("<Esc>", M.escape, "put the problem away, or close")
  -- Temporary unless sticky: leaving it closes it. Scheduled, because a window cannot be closed
  -- from inside the event that is leaving it.
  vim.api.nvim_create_autocmd("WinLeave", {
    buffer = buf,
    callback = function()
      vim.schedule(function()
        if not M.is_sticky() and not focused() then
          M.close()
        end
      end)
    end,
  })
  vim.api.nvim_create_autocmd("CursorMoved", { buffer = buf, callback = mark_selection })
  return buf
end

-- Open the panel, or move into it when it is already open. ONLY reached from a user command or
-- keymap.
function M.open(root, only)
  state.root, state.only = root, only
  if M.is_open() then
    if not focused() then
      state.origin = vim.api.nvim_get_current_win()
      vim.api.nvim_set_current_win(state.win)
    end
    M.refresh(root)
    return
  end
  state.origin = vim.api.nvim_get_current_win()
  ensure_buffer()
  place_window(render())
  if items[1] then
    vim.api.nvim_win_set_cursor(state.win, { items[1].first, 0 })
  end
  mark_selection()
end

-- From inside the panel: close it. From anywhere else: open it, or go into it if it is open.
function M.toggle(root, only)
  if focused() then
    M.close()
  else
    M.open(root or state.root, only)
  end
end

-- Stick or unstick for this session; nil toggles. Sticking a closed panel opens it without
-- taking the cursor, since the point is to keep it in view while coding. Unsticking a panel the
-- cursor is not in closes it: nothing else would.
function M.set_sticky(on, root)
  if on == nil then
    on = not M.is_sticky()
  end
  state.sticky = on
  root = root or state.root
  if on and not M.is_open() and root then
    local here = vim.api.nvim_get_current_win()
    M.open(root, state.only)
    vim.api.nvim_set_current_win(here)
  elseif not on and M.is_open() and not focused() then
    M.close()
  else
    M.refresh()
  end
end

return M
