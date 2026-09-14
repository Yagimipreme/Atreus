-- Layer 3a: the findings store. Holds the last complete set the engine published, grouped by
-- surface, and nothing else. It was previously called `render` and also owned a window per
-- surface; the windows moved to panel.lua, which is the only thing that draws now.
--
-- findings.jsonl is rewritten whole by the engine, so loading is a replacement, never a merge:
-- a finding that stops being published has stopped being true.
local util = require("companion.util")

local M = {}

M.SURFACES = { "callers", "errors", "docs", "roadmap" }

local function empty()
  local t = {}
  for _, name in ipairs(M.SURFACES) do
    t[name] = {}
  end
  return t
end

M.findings = empty()

-- Replace everything from one findings.jsonl payload. A malformed line is skipped rather than
-- allowed to discard the rest: half a file is still worth showing, and the engine rewrites
-- atomically so this should not happen at all.
function M.load(data)
  local by_surface = empty()
  for line in data:gmatch("[^\n]+") do
    local f = util.decode_json(line)
    if type(f) == "table" and f.surface and by_surface[f.surface] then
      table.insert(by_surface[f.surface], f)
    end
  end
  M.findings = by_surface
  return by_surface
end

function M.count()
  local n = 0
  for _, items in pairs(M.findings) do
    n = n + #items
  end
  return n
end

function M.clear()
  M.findings = empty()
end

return M
