-- Small helpers shared by the layers. No Neovim state is owned here.
local M = {}

-- Debounce: returns a function that, however often you call it, runs `fn` once after `ms`
-- milliseconds of quiet. Uses libuv timers (vim.uv), not vim.fn.timer_start, because we want
-- the same primitive available in fast contexts.
--
-- The callback runs inside vim.schedule so it may touch buffers and call the API safely:
-- libuv callbacks fire on the event loop where most vim.api calls are forbidden.
function M.debounce(ms, fn)
  local timer = nil
  return function(...)
    local args = { ... }
    if timer then
      timer:stop()
      timer:close()
      timer = nil
    end
    timer = vim.uv.new_timer()
    timer:start(ms, 0, function()
      if timer then
        timer:stop()
        timer:close()
        timer = nil
      end
      vim.schedule(function()
        fn(unpack(args))
      end)
    end)
  end
end

-- Workspace root for a buffer: nearest ancestor containing one of these markers.
-- vim.fs.find with upward=true walks up from `path`. Falls back to the file's directory.
local MARKERS = { ".git", "Cargo.toml", "pyproject.toml", "package.json", "go.mod" }

function M.workspace_root(path)
  if path == nil or path == "" then
    return nil
  end
  local found = vim.fs.find(MARKERS, { path = vim.fs.dirname(path), upward = true })[1]
  return found and vim.fs.dirname(found) or vim.fs.dirname(path)
end

-- Path relative to root, so events and findings never carry absolute paths.
function M.relative(root, path)
  if root and path:sub(1, #root + 1) == root .. "/" then
    return path:sub(#root + 2)
  end
  return path
end

-- Neovim is 0-based for columns and (in the API) 0-based for lines; the contract is 1-based
-- for both. Convert at the boundary, exactly once, here.
function M.to_contract_pos(line0, col0)
  return line0 + 1, col0 + 1
end

function M.from_contract_pos(line1, col1)
  return line1 - 1, col1 - 1
end

-- Canonical text. The engine hashes files as they sit on disk, so a buffer's hash has to be
-- the hash of the bytes Neovim *would* write for it -- otherwise every hash stops matching the
-- moment the developer saves. 'fileformat' gives the separator and 'eol' says whether the
-- last line is terminated -- including for an empty buffer, which holds one empty line and so
-- becomes one separator, or nothing at all when 'eol' is off. The rule and its
-- fixtures live in docs/text-canon.md and tests/fixtures/text-canon.json; both sides are
-- checked against a real :write by scripts/check-workflow.py.
local SEPARATOR = { unix = "\n", dos = "\r\n", mac = "\r" }

function M.canonical_text(buf)
  local lines = vim.api.nvim_buf_get_lines(buf, 0, -1, false)
  if #lines == 0 then
    return ""
  end
  local sep = SEPARATOR[vim.bo[buf].fileformat] or "\n"
  local text = table.concat(lines, sep)
  if vim.bo[buf].eol then
    text = text .. sep
  end
  return text
end

-- sha256 truncated to 16 hex chars: the same digest and width the Python snapshot store uses,
-- so an editor hash and an engine hash of the same bytes are directly comparable.
function M.text_sha(text)
  return vim.fn.sha256(text):sub(1, 16)
end

-- vim.json.decode turns JSON null into vim.NIL, a userdata sentinel, so that a null inside an
-- array does not silently shorten it. Every field the engine writes is present-with-null when
-- it has no value, so without this `(engine.model.name or "none")` yields the sentinel and the
-- next concatenation throws. Decode through here and absent means absent.
function M.decode_json(data)
  local ok, decoded = pcall(vim.json.decode, data)
  if not ok then
    return nil
  end
  local function strip(v)
    if type(v) ~= "table" then
      return v ~= vim.NIL and v or nil
    end
    for k, item in pairs(v) do
      v[k] = strip(item)
    end
    return v
  end
  return strip(decoded)
end

-- Unique per Neovim instance without relying on math.random, which LuaJIT does not seed.
-- Two instances cannot share a pid at the same second, and a reused pid cannot recur within
-- the same second, so (start time, pid) is unique on a machine. Opaque to the engine — it is
-- compared, never parsed.
function M.session_id()
  return string.format("%x-%x", os.time(), vim.fn.getpid())
end

function M.notify(msg, level)
  vim.notify("[companion] " .. msg, level or vim.log.levels.INFO)
end

return M
