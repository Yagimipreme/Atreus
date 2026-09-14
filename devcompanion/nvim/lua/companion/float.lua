-- Shared by the panel and the info view: highlight groups, a line builder that carries its own
-- highlights, width-aware cutting and wrapping, and opening a float. Nothing here decides what
-- is shown.
local config = require("companion.config")

local M = {}

M.ns = vim.api.nvim_create_namespace("companion")

-- Linked, never coloured: the companion should look like part of whatever colourscheme is on.
-- Colour is semantic and scarce. Red marks the value that is wrong, not the sentence about it.
local LINKS = {
  CompanionTitle = "FloatTitle",
  CompanionError = "DiagnosticError",
  CompanionWarn = "DiagnosticWarn",
  CompanionOk = "DiagnosticOk",
  CompanionMuted = "Comment",
  CompanionLocation = "Directory",
  CompanionKey = "Special",
  CompanionIndex = "LineNr",
  CompanionSymbol = "Function",       -- the function or name a problem is about
  CompanionExpected = "DiagnosticOk", -- what the code needs
  CompanionGot = "DiagnosticError",   -- what the code has instead
  CompanionSelected = "CursorLine",   -- the selected problem, in place of a cursor
  CompanionSource = "Visual",         -- the selected problem's range, in the code
  CompanionBorderActive = "DiagnosticInfo", -- the panel has the keyboard
  CompanionBorder = "Comment",              -- the panel is only in view
}

function M.highlights()
  for name, link in pairs(LINKS) do
    vim.api.nvim_set_hl(0, name, { link = link, default = true })
  end
  -- Not a link: a cursor highlight with full blend is how the terminal cursor is hidden.
  vim.api.nvim_set_hl(0, "CompanionHiddenCursor", { blend = 100, nocombine = true })
end

M.highlights()
vim.api.nvim_create_autocmd("ColorScheme", {
  group = vim.api.nvim_create_augroup("companion:highlights", { clear = true }),
  callback = M.highlights,
})

-- nvim_buf_set_lines raises on a string containing a newline, which would take down the whole
-- view. The engine flattens its fields, but this is a rendering boundary and it must hold
-- whatever it is handed: a view that shows an awkward line is a nuisance, one that throws is a
-- broken tool.
local function flatten(s)
  return (tostring(s):gsub("[\r\n]+", " "))
end

-- ---------------------------------------------------------------- lines with highlights

local Canvas = {}
Canvas.__index = Canvas

function M.canvas()
  return setmetatable({ lines = {}, marks = {} }, Canvas)
end

-- Append one line built from parts: a string, or a list of { text, highlight-group? }.
-- Returns the 1-based line number it landed on.
function Canvas:add(parts)
  if type(parts) == "string" then
    parts = { { parts } }
  end
  local text = ""
  for _, part in ipairs(parts) do
    local s = flatten(part[1] or "")
    if part[2] and s ~= "" then
      table.insert(self.marks, { #self.lines, #text, #text + #s, part[2] })
    end
    text = text .. s
  end
  table.insert(self.lines, text)
  return #self.lines
end

-- Highlight a byte range of an existing line (1-based line number). `priority` decides which of
-- two overlapping marks shows, e.g. an error range over Tree-sitter's syntax colours.
function Canvas:mark(lnum, from, to, group, priority)
  local len = #(self.lines[lnum] or "")
  from, to = math.min(from, len), math.min(to, len)
  if from < to then
    table.insert(self.marks, { lnum - 1, from, to, group, priority })
  end
end

-- A blank line, unless the last one already is.
function Canvas:gap()
  if #self.lines > 0 and self.lines[#self.lines] ~= "" then
    self:add("")
  end
end

-- Drop trailing blank lines.
function Canvas:trim()
  while #self.lines > 0 and self.lines[#self.lines] == "" do
    table.remove(self.lines)
  end
end

function M.draw(buf, canvas)
  vim.bo[buf].modifiable = true
  vim.api.nvim_buf_set_lines(buf, 0, -1, false, canvas.lines)
  vim.bo[buf].modifiable = false
  vim.api.nvim_buf_clear_namespace(buf, M.ns, 0, -1)
  for _, m in ipairs(canvas.marks) do
    if m[1] < #canvas.lines then
      vim.api.nvim_buf_set_extmark(buf, M.ns, m[1], m[2], { end_col = m[3], hl_group = m[4], priority = m[5] })
    end
  end
end

-- ---------------------------------------------------------------- columns, not bytes

function M.width(s)
  return vim.fn.strdisplaywidth(s)
end

function M.truncate(s, width)
  s = flatten(s or "")
  if width <= 0 then
    return ""
  end
  if M.width(s) <= width then
    return s
  end
  local n = width - 1
  local out = vim.fn.strcharpart(s, 0, n)
  while n > 0 and M.width(out) > width - 1 do -- a wide character takes two columns
    n = n - 1
    out = vim.fn.strcharpart(s, 0, n)
  end
  return out .. "…"
end

function M.wrap(text, width)
  local out, cur = {}, ""
  for word in flatten(text or ""):gmatch("%S+") do
    local candidate = cur == "" and word or (cur .. " " .. word)
    if M.width(candidate) <= width then
      cur = candidate
    else
      if cur ~= "" then
        table.insert(out, cur)
      end
      cur = word
      while M.width(cur) > width do
        table.insert(out, vim.fn.strcharpart(cur, 0, width))
        cur = vim.fn.strcharpart(cur, width)
      end
    end
  end
  if cur ~= "" then
    table.insert(out, cur)
  end
  return out
end

-- ---------------------------------------------------------------- windows

function M.scratch(name)
  local buf = vim.api.nvim_create_buf(false, true) -- unlisted, scratch, never written to disk
  vim.bo[buf].bufhidden = "hide"
  vim.bo[buf].filetype = "companion"
  vim.bo[buf].modifiable = false
  vim.api.nvim_buf_set_name(buf, name)
  return buf
end

-- A float needs a border to carry a title and a footer, so "none" is not an answer here.
function M.border()
  if config.options.ui.border then
    return config.options.ui.border
  end
  local ok, wb = pcall(function() return vim.o.winborder end)
  return (ok and wb and wb ~= "" and wb ~= "none") and wb or "rounded"
end

-- Open `buf` in a float and focus it. `cfg` is nvim_open_win's geometry plus title/footer.
function M.open(buf, cfg)
  local win = vim.api.nvim_open_win(buf, true, vim.tbl_extend("force", {
    style = "minimal",
    border = M.border(),
    zindex = 45,
  }, cfg))
  vim.wo[win].wrap = false
  vim.wo[win].cursorline = false
  return win
end

return M
