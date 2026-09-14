-- Layer 3b: THE PANEL. The companion's quick-help surface: a small float at the right edge of
-- the editor holding a short, prioritised list of problems.
--
-- One problem is two lines, one inspected problem at a time, raw evidence only on request. The
-- engine has already grouped the language server's messages into problems and said each as a
-- sentence with its facts named (present/problems.py); this module lays that out and spends
-- colour only where the eye should go: the symbol, what the code needs, what it has instead.
--
-- It is a view, never a source: it renders the findings store and owns only its window, which
-- problem is inspected, and where the cursor is. Engine metadata is not here; see info.lua.
--
-- It opens only when the developer asks. Having been asked, it takes focus -- its keys act
-- inside it -- and it closes on q, a jump, or leaving it, handing the cursor back to the window
-- it was opened from. Pinned (`ui.pinned`, :CompanionPanelPin, `p`) it stays open on leaving and
-- after a jump, and follows the code: the problem on the cursor's line opens in place, and the
-- problem selected in the panel is highlighted in the code. Nothing moves the cursor but ↵.
local config = require("companion.config")
local util = require("companion.util")
local store = require("companion.findings")
local float = require("companion.float")

local M = {}

local state = { buf = nil, win = nil, root = nil, origin = nil, only = nil, pinned = nil }
local open = { id = nil, raw = false } -- the one inspected problem, and whether its raw evidence shows
local items = {}                        -- as drawn: { first, head, last, finding }
-- Following the code cursor: the problem it opened, what was open before it did, and the line it
-- last looked at -- so moving within a line does no work and moving off restores what was there.
local follow = { id = nil, previous = nil, at = nil }

local function unfollow()
  follow.id, follow.previous, follow.at = nil, nil, nil
end
local footer_key = nil                  -- the footer last applied; cursor moves redraw it only on change
local saved_guicursor = nil             -- 'guicursor' while the panel hides the cursor
local source_buf = nil                  -- the code buffer carrying the selected problem's range
local selection = vim.api.nvim_create_namespace("companion.selection")
local source_ns = vim.api.nvim_create_namespace("companion.source")

-- " ▸ E  " -- marker, letter, then the place and the sentence from this column.
local INDENT = 6
local PAD = string.rep(" ", INDENT)
local LABEL = 11 -- "defined in" and a space
local LETTER = { test_result = "T", caller_affected = "C", diagnostic_context = "E" }
local SKIP_CAPTURE = { spell = true, nospell = true, conceal = true }

-- One vocabulary for what a problem is made of, in one order, so the block under an opened
-- problem reads the same every time: what the code has (red), what it needs (green), where.
local FACT_ROWS = {
  { "got", "CompanionGot" }, { "found", "CompanionGot" }, { "returned", "CompanionGot" },
  { "missing", "CompanionGot" }, { "expected", "CompanionExpected" },
  { "required", "CompanionExpected" }, { "operator" }, { "with" }, { "left" }, { "right" },
  { "parameter" }, { "argument" }, { "function", "CompanionSymbol" }, { "module" },
  { "defined in" },
}
local SENTENCE_HL = {
  symbol = "CompanionSymbol", ["function"] = "CompanionSymbol",
  got = "CompanionGot", found = "CompanionGot", returned = "CompanionGot", missing = "CompanionGot",
  expected = "CompanionExpected", required = "CompanionExpected",
}

function M.is_open()
  return state.win ~= nil and vim.api.nvim_win_is_valid(state.win)
end

local function focused()
  return M.is_open() and vim.api.nvim_get_current_win() == state.win
end

-- The workspace the panel was last opened for, or nil.
function M.root()
  return state.root
end

-- The session's choice when one was made, otherwise the configured default.
function M.is_pinned()
  if state.pinned ~= nil then
    return state.pinned
  end
  return config.options.ui.pinned == true
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

-- The line a location points at, as it is now: from the buffer when it is loaded, else the file.
local function source_line(root, loc)
  if not (loc and loc.path and loc.line) then
    return nil
  end
  local abs = root .. "/" .. loc.path
  local buf = vim.fn.bufnr(abs)
  if buf ~= -1 and vim.api.nvim_buf_is_loaded(buf) then
    return vim.api.nvim_buf_get_lines(buf, loc.line - 1, loc.line, false)[1]
  elseif vim.fn.filereadable(abs) == 1 then
    return vim.fn.readfile(abs, "", loc.line)[loc.line]
  end
end

-- The byte range a location covers on its own line: to its end when that is on the same line,
-- to the end of the line when it runs on, otherwise the token at its column.
local function span(text, loc)
  if not loc.col then
    return 0, #text
  end
  local s = math.min(math.max(loc.col - 1, 0), #text)
  local e
  if loc.end_line == loc.line and loc.end_col and loc.end_col > loc.col then
    e = loc.end_col - 1
  elseif loc.end_line and loc.end_line > loc.line then
    e = #text
  else
    local word = text:sub(s + 1):match("^[%w_]+")
    e = s + (word and #word or 1)
  end
  return s, math.min(math.max(e, s + 1), #text)
end

-- ---------------------------------------------------------------- rows

-- Byte spans of the facts inside a sentence, in order. `got` is taken at its last occurrence,
-- because sentences end with it; the others at their first.
local function fact_spans(text, facts)
  local spans = {}
  for key, group in pairs(SENTENCE_HL) do
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

-- The sentence with each fact in its own colour; everything else plain, because a sentence that
-- is all red tells the eye nothing. Collapsed it is one line, cut if it must be; opened, whole.
local function sentence_rows(c, text, facts, width, dim, one_line)
  local room = width - INDENT - 1
  if one_line then
    text = float.truncate(text, room)
  end
  local spans = fact_spans(text, facts)
  local offset = 0
  for _, l in ipairs(float.wrap(text, room)) do
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

-- The line of code, syntax-highlighted by Tree-sitter when a parser for it is installed, with
-- the problem's own range in the colour of what is wrong on top, and a caret under it. Returns
-- whether there was a line to show.
local function code_rows(c, root, loc, width)
  local text = source_line(root, loc)
  if not text or not text:find("%S") then
    return false
  end
  local indent = #text:match("^%s*")
  local body = text:sub(indent + 1)
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
          c:mark(row, INDENT + sc, INDENT + (er == 0 and ec or #shown), "@" .. name .. "." .. lang, 100)
        end
      end
    end)
  end
  if loc.col then
    local s, e = span(text, loc)
    s, e = math.max(0, s - indent), math.max(0, e - indent)
    c:mark(row, INDENT + s, INDENT + e, "CompanionGot", 200)
    local caret = float.width(body:sub(1, s))
    if caret < room then
      c:add({ { PAD .. string.rep(" ", caret) }, { "^", "CompanionGot" } })
    end
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

-- ↵: the problem, not its paperwork. The code, what it has against what it needs, what changed,
-- a likely fix when a model offered one.
local function inspected(c, root, f, stale, width)
  c:gap()
  if code_rows(c, root, f.location, width) then
    c:gap()
  end
  local facts, any = f.facts or {}, false
  for _, row in ipairs(FACT_ROWS) do
    local value = facts[row[1]]
    if type(value) == "string" and value ~= "" then
      kv(c, row[1], value, row[2], width)
      any = true
    end
  end
  if any then
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
  local fix = not stale and store.fix(root, f)
  if fix then
    local warned = #(fix.warnings or {})
    local covers = #(fix.covers or {})
    local warning = warned > 0 and (warned .. (warned == 1 and " new warning" or " new warnings")) or nil
    -- `✓ fix checked · 1 new warning`, or with a fix that resolves several problems, their count on
    -- the line and the warnings under it, so neither is cut at the panel's edge.
    c:add({ { PAD }, { "✓", "CompanionOk" }, { " fix checked", "CompanionMuted" },
      { covers > 1 and (" · " .. covers .. " problems") or (warning and (" · " .. warning) or ""),
        covers > 1 and "CompanionMuted" or "CompanionWarn" },
      { "   f", "CompanionKey" }, { " review", "CompanionMuted" } })
    if covers > 1 and warning then
      c:add({ { PAD }, { warning, "CompanionWarn" } })
    end
    c:gap()
  end
  if open.raw then
    raw_rows(c, f, stale, width)
  end
end

-- Returns the problem's first line and the last line of its two-line head.
local function item(c, root, entry, width)
  local f, stale = entry.finding, entry.stale
  local dim = stale and "CompanionMuted" or nil
  local inferred = f.basis == "inferred"
  local is_open = open.id == f.id
  -- The right edge: what the claim rests on when that matters, otherwise that a checked fix waits.
  local tag
  if stale then
    tag = { { "stale", "CompanionMuted" } }
  elseif unsaved(f) then
    tag = { { "unsaved", "CompanionMuted" } }
  elseif store.fix(root, f) then
    tag = { { "✓", "CompanionOk" }, { " fix checked", "CompanionMuted" } }
  end
  local tag_width = 0
  for _, part in ipairs(tag or {}) do
    tag_width = tag_width + float.width(part[1])
  end
  local where = float.truncate(place(f), width - INDENT - 1 - (tag and tag_width + 2 or 0))
  local row = {
    { " " },
    { is_open and "▼" or " ", "CompanionKey" },
    { " " },
    { inferred and "?" or (LETTER[f.kind] or "•"), dim or (inferred and "CompanionWarn" or "CompanionError") },
    { "  " },
    { where, dim or "CompanionLocation" },
  }
  if tag then
    table.insert(row, { string.rep(" ", math.max(2, width - INDENT - float.width(where) - tag_width - 1)) })
    vim.list_extend(row, tag)
  end
  local first = c:add(row)
  sentence_rows(c, sentence(f), f.facts, width, dim, not is_open)
  local head = #c.lines
  if is_open then
    inspected(c, root, f, stale, width)
  end
  return first, head
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
  -- count stands for, dimmed: the problem count is the human number, this one supports it.
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
  local fixable = #store.fixable(root, state.only)
  if fixable > 0 then
    c:add({ { " " }, { "✓", "CompanionOk" }, { " I can fix " .. fixable .. " of these", "CompanionMuted" },
      { " · ", "CompanionMuted" }, { "f", "CompanionKey" }, { " review", "CompanionMuted" } })
  end

  local max = config.options.ui.max_findings
  for i, entry in ipairs(list) do
    c:gap()
    if i > max then
      c:add({ { PAD }, { "… " .. (#list - max) .. " more", "CompanionMuted" } })
      break
    end
    local first, head = item(c, root, entry, width)
    c:trim()
    table.insert(items, { first = first, head = head, last = #c.lines, finding = entry.finding })
  end

  float.draw(state.buf, c)
  return #c.lines
end

local function title()
  local chunks = { { " companion ", "CompanionTitle" } }
  if M.is_pinned() then
    table.insert(chunks, { "📌 ", "CompanionMuted" })
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

-- How to get back into the panel: the developer's own mapping for :CompanionPanel when there is
-- one, so the hint names the keys they actually press.
local function enter_key()
  for _, m in ipairs(vim.api.nvim_get_keymap("n")) do
    local rhs = (m.rhs or ""):lower()
    if rhs == "<cmd>companionpanel<cr>" or rhs == ":companionpanel<cr>" then
      return (vim.fn.keytrans(m.lhs):gsub("<Space>", "␣"))
    end
  end
  return ":CompanionPanel"
end

-- The keys that do something where the cursor is. Only keys that exist: `f review` only on a
-- problem with a checked fix. With the cursor elsewhere, the only useful key is the way back in.
local function footer()
  local cur = M.is_open() and item_at(vim.api.nvim_win_get_cursor(state.win)[1]) or nil
  local keys
  if M.is_open() and not focused() then
    keys = { { enter_key(), "focus" } }
  elseif #items == 0 then
    keys = { { "q", "close" } }
  elseif cur and cur.finding.id == open.id then
    keys = { { "↵", "go to" }, { "d", open.raw and "hide raw" or "raw" }, { "h", "back" }, { "q", "close" } }
  else
    keys = { { "↵", "inspect" }, { "p", M.is_pinned() and "unpin" or "pin" }, { "q", "close" } }
  end
  if cur and focused() and store.fix(state.root, cur.finding) then
    table.insert(keys, 1, { "f", "review" })
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

-- ---------------------------------------------------------------- cursor and code

-- Which window has the keyboard has to be visible at a glance, because the cursor is hidden
-- inside the panel: a bright border while it has focus, a quiet one while it is only in view.
local function paint_focus()
  if M.is_open() then
    vim.wo[state.win].winhighlight = "FloatBorder:" .. (focused() and "CompanionBorderActive" or "CompanionBorder")
  end
end

-- Inside the panel the terminal cursor is hidden: the selected problem's background and marker
-- say where you are, and a block cursor on top of them reads as a text cursor in a text buffer.
-- Normal and visual mode only, so a command line typed from the panel still shows its cursor.
local function hide_cursor()
  if saved_guicursor == nil then
    saved_guicursor = vim.o.guicursor
    vim.o.guicursor = (saved_guicursor ~= "" and (saved_guicursor .. ",") or "") .. "n-v:block-CompanionHiddenCursor"
  end
end

local function show_cursor()
  if saved_guicursor ~= nil then
    vim.o.guicursor = saved_guicursor
    saved_guicursor = nil
  end
end

local function clear_source()
  if source_buf and vim.api.nvim_buf_is_valid(source_buf) then
    vim.api.nvim_buf_clear_namespace(source_buf, source_ns, 0, -1)
  end
  source_buf = nil
end

-- Panel -> code: the selected problem's range, highlighted where it is, without moving any
-- cursor. Only while the panel has focus; while coding, the line under the cursor needs no mark.
local function mark_source(f)
  clear_source()
  local loc = f and f.location
  if not (focused() and loc and loc.path and loc.line) then
    return
  end
  local buf = vim.fn.bufnr(state.root .. "/" .. loc.path)
  if buf == -1 or not vim.api.nvim_buf_is_loaded(buf) or loc.line > vim.api.nvim_buf_line_count(buf) then
    return
  end
  local text = vim.api.nvim_buf_get_lines(buf, loc.line - 1, loc.line, false)[1] or ""
  local s, e = span(text, loc)
  if e > s then
    vim.api.nvim_buf_set_extmark(buf, source_ns, loc.line - 1, s, { end_col = e, hl_group = "CompanionSource", priority = 250 })
    source_buf = buf
  end
end

-- The selected problem gets a quiet background on its two-line head and a marker; its range is
-- marked in the code; the footer follows. None of it redraws the list.
local function mark_selection()
  if not M.is_open() then
    return
  end
  vim.api.nvim_buf_clear_namespace(state.buf, selection, 0, -1)
  local cur = item_at(vim.api.nvim_win_get_cursor(state.win)[1])
  if cur then
    for lnum = cur.first, cur.head do
      vim.api.nvim_buf_set_extmark(state.buf, selection, lnum - 1, 0, { line_hl_group = "CompanionSelected", priority = 10 })
    end
    vim.api.nvim_buf_set_extmark(state.buf, selection, cur.first - 1, 1, {
      virt_text = { { cur.finding.id == open.id and "▼" or "▸", "CompanionKey" } },
      virt_text_pos = "overlay",
    })
  end
  mark_source(cur and cur.finding)
  local keys = footer()
  local key = vim.inspect(keys)
  if key ~= footer_key then
    footer_key = key
    vim.api.nvim_win_set_config(state.win, { footer = keys, footer_pos = "right" })
  end
end

-- Put the panel's cursor on a problem's first row, and scroll so as much of it as fits is in view.
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
  show_cursor()
  clear_source()
  unfollow()
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
  if not M.is_pinned() then
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
  unfollow()
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
  unfollow()
  M.refresh()
  show_item(it.finding.id)
end

-- <Esc>: out of the panel, in one key whatever is open. A pinned panel stays in view and the
-- cursor goes back to the code; an unpinned one closes.
function M.leave()
  if not M.is_pinned() then
    return M.close()
  end
  if state.origin and vim.api.nvim_win_is_valid(state.origin) and state.origin ~= state.win then
    vim.api.nvim_set_current_win(state.origin)
  else
    vim.cmd("wincmd p")
  end
end

-- f: review the checked fix on this problem, or the first one listed; `n` in the review moves on.
function M.review()
  local list = store.fixes(state.root, state.only)
  if #list == 0 then
    return
  end
  local it = M.is_open() and item_at(vim.api.nvim_win_get_cursor(state.win)[1]) or nil
  local here = it and store.fix(state.root, it.finding) and store.fix_key(it.finding)
  local index = 1
  for i, f in ipairs(list) do
    if here and store.fix_key(f) == here then
      index = i
    end
  end
  require("companion.review").open(state.root, list, index, state.origin)
end

-- h: put the inspected problem away, staying in the panel.
function M.collapse()
  if not open.id then
    return
  end
  local id = open.id
  open.id, open.raw = nil, false
  unfollow()
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

-- Code -> panel. With the panel open and the cursor in the code (pinned), the problem on the
-- cursor's line is opened in place, and moving off puts back whatever was open before. A
-- problem that is already open -- by hand or by following -- is only selected, never taken
-- away. Called on CursorMoved.
function M.follow(root, buf, lnum)
  if not M.is_open() or focused() or state.root ~= root then
    return
  end
  local rel = util.relative(root, vim.api.nvim_buf_get_name(buf))
  local at = rel .. ":" .. lnum
  if at == follow.at then
    return
  end
  follow.at = at
  local match
  for _, it in ipairs(items) do
    local loc = it.finding.location
    if loc and loc.path == rel and loc.line == lnum then
      match = it
      break
    end
  end
  if match and open.id == match.finding.id then
    show_item(match.finding.id)
  elseif match then
    if follow.id == nil then
      follow.previous = open.id
    end
    follow.id = match.finding.id
    open.id, open.raw = follow.id, false
    M.refresh()
    show_item(follow.id)
  elseif follow.id then
    if open.id == follow.id then
      open.id, open.raw = follow.previous, false
    end
    follow.id, follow.previous = nil, nil
    M.refresh()
    if open.id then
      show_item(open.id)
    end
  end
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
  map("f", M.review, "review the checked fix")
  map("j", function() M.step(1) end, "next problem")
  map("k", function() M.step(-1) end, "previous problem")
  map("p", function() M.set_pinned() end, "pin or unpin")
  map("r", function() M.refresh() end, "redraw")
  map("h", M.collapse, "put the inspected problem away")
  map("<BS>", M.collapse, "put the inspected problem away")
  map("q", M.close, "close")
  map("<Esc>", M.leave, "leave the panel")
  vim.api.nvim_create_autocmd("WinEnter", {
    buffer = buf,
    callback = function()
      hide_cursor()
      paint_focus()
      mark_selection()
    end,
  })
  -- Temporary unless pinned: leaving it closes it. Scheduled, because a window cannot be closed
  -- from inside the event that is leaving it; a pinned panel is repainted as unfocused instead.
  vim.api.nvim_create_autocmd("WinLeave", {
    buffer = buf,
    callback = function()
      show_cursor()
      clear_source()
      vim.schedule(function()
        if not M.is_pinned() and not focused() then
          M.close()
        elseif not focused() then
          paint_focus()
          mark_selection()
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
  hide_cursor()
  paint_focus()
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

-- Pin or unpin for this session; nil toggles. Pinning a closed panel opens it without taking
-- the cursor, since the point is to keep it in view while coding. Unpinning a panel the cursor
-- is not in closes it: nothing else would.
function M.set_pinned(on, root)
  if on == nil then
    on = not M.is_pinned()
  end
  state.pinned = on
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
