-- Layer 1: COLLECT. Turns editor events into contract events. This is the module that knows
-- Neovim's API; everything downstream sees only plain tables.
--
-- Nothing here does work: each autocmd builds a small table and hands it to transport.
-- Expensive things (reading the whole buffer) happen inside the debounced callback, not in
-- the autocmd itself, so typing is never slowed.
local util = require("companion.util")
local config = require("companion.config")
local transport = require("companion.transport")

local M = {}

-- One augroup per workspace so stop() can clear exactly what start() created.
local groups = {}

local function should_observe(buf)
  if not vim.api.nvim_buf_is_valid(buf) then
    return false
  end
  -- Only real files: skip terminals, help, quickfix, our own surfaces.
  if vim.bo[buf].buftype ~= "" then
    return false
  end
  local name = vim.api.nvim_buf_get_name(buf)
  if name == "" or name:match("/%.companion/") then
    return false
  end
  local fts = config.options.filetypes
  if #fts > 0 and not vim.tbl_contains(fts, vim.bo[buf].filetype) then
    return false
  end
  return true
end

-- Build the shared per-buffer fields once. fileformat/eol travel with every event because
-- they are what makes `text` reproducible as bytes on the engine side.
local function buffer_ref(root, buf)
  local abs = vim.api.nvim_buf_get_name(buf)
  return {
    path = util.relative(root, abs),
    doc_version = vim.b[buf].changedtick,
    bufnr = buf,
    language = vim.bo[buf].filetype,
    dirty = vim.bo[buf].modified,
    fileformat = vim.bo[buf].fileformat,
    eol = vim.bo[buf].eol,
  }
end

-- Attach the buffer's canonical bytes and their hash. The engine stores content by hash, so
-- these two fields are what turn an unsaved buffer into something it can analyse.
local function attach_text(ev, buf)
  ev.text = util.canonical_text(buf)
  ev.text_sha = util.text_sha(ev.text)
  return ev
end

-- vim.diagnostic.get returns Neovim's normalized diagnostics from every attached source
-- (LSP, linters via null-ls, anything using the diagnostic API). Positions are 0-based.
local SEVERITY = { "error", "warn", "info", "hint" }

local function diagnostics_for(buf)
  local items = {}
  for _, d in ipairs(vim.diagnostic.get(buf)) do
    local line, col = util.to_contract_pos(d.lnum, d.col)
    local end_line, end_col = util.to_contract_pos(d.end_lnum or d.lnum, d.end_col or d.col)
    table.insert(items, {
      line = line,
      col = col,
      end_line = end_line,
      end_col = end_col,
      severity = SEVERITY[d.severity] or "info",
      code = d.code and tostring(d.code) or nil,
      source = d.source,
      message = d.message,
    })
  end
  return items
end

function M.start(root)
  if groups[root] then
    return groups[root]
  end
  local tr = transport.for_workspace(root)
  local group = vim.api.nvim_create_augroup("companion:" .. root, { clear = true })
  groups[root] = group

  -- Debounced senders. Each is created once and closes over the transport.
  local send_text = util.debounce(config.options.debounce.text, function(buf)
    if not should_observe(buf) then
      return
    end
    local ev = buffer_ref(root, buf)
    ev.kind = "buffer_changed"
    attach_text(ev, buf)
    tr:send(ev)
  end)

  local send_diags = util.debounce(config.options.debounce.diagnostics, function(buf)
    if not should_observe(buf) then
      return
    end
    local ev = buffer_ref(root, buf)
    ev.kind = "diagnostics"
    ev.items = diagnostics_for(buf)
    ev.text = nil
    tr:send(ev)
  end)

  local send_cursor = util.debounce(config.options.debounce.cursor, function(buf, line, col)
    if not should_observe(buf) then
      return
    end
    local ev = buffer_ref(root, buf)
    ev.kind = "cursor"
    ev.line = line
    ev.col = col
    tr:send(ev)
  end)

  -- TextChanged fires after a change in normal mode; TextChangedI while inserting.
  -- Both are cheap to receive: the debounce decides when we actually read the buffer.
  vim.api.nvim_create_autocmd({ "TextChanged", "TextChangedI" }, {
    group = group,
    callback = function(a)
      send_text(a.buf)
    end,
  })

  -- A save is worth sending immediately: it is a deliberate act and the engine may want to
  -- run tools that read from disk.
  vim.api.nvim_create_autocmd("BufWritePost", {
    group = group,
    callback = function(a)
      if not should_observe(a.buf) then
        return
      end
      local ev = buffer_ref(root, a.buf)
      ev.kind = "buffer_saved"
      attach_text(ev, a.buf)
      ev.dirty = false
      tr:send(ev)
    end,
  })

  -- DiagnosticChanged is the whole reason the adapter is worth having: the editor already
  -- holds the language server's answers.
  vim.api.nvim_create_autocmd("DiagnosticChanged", {
    group = group,
    callback = function(a)
      send_diags(a.buf)
    end,
  })

  -- Leaving takes the unsaved buffers with it. Without this the engine would go on reporting
  -- overlay content that no longer exists anywhere, which is the one thing a freshness model
  -- must never do. Sent synchronously: there is no later.
  vim.api.nvim_create_autocmd("VimLeavePre", {
    group = group,
    callback = function()
      tr:send_sync({ kind = "session_end" })
    end,
  })

  -- CursorHold is already gated by 'updatetime'; the debounce is a floor on top of it.
  vim.api.nvim_create_autocmd("CursorHold", {
    group = group,
    callback = function(a)
      local pos = vim.api.nvim_win_get_cursor(0)
      send_cursor(a.buf, pos[1], pos[2] + 1)
    end,
  })

  M.announce_open_buffers(root, tr)
  return group
end

-- Buffers that were already open when observation started have never fired an autocmd, so the
-- engine would not learn about them until the next edit — and for a buffer with unsaved work
-- sitting in it, possibly never. Send each one once at start.
--
-- Bounded by the number of open buffers, which is small, and each send is an async append.
function M.announce_open_buffers(root, tr)
  local sent = 0
  for _, buf in ipairs(vim.api.nvim_list_bufs()) do
    if vim.api.nvim_buf_is_loaded(buf) and should_observe(buf) then
      local name = vim.api.nvim_buf_get_name(buf)
      -- Only this workspace: one Neovim often holds buffers from several projects.
      if name:sub(1, #root + 1) == root .. "/" then
        local ev = buffer_ref(root, buf)
        -- A modified buffer is the interesting case; a clean one just seeds the baseline.
        ev.kind = ev.dirty and "buffer_changed" or "buffer_saved"
        attach_text(ev, buf)
        tr:send(ev)
        -- The same for what the language server already said: DiagnosticChanged fired before
        -- anyone was listening, and it will not fire again until the next edit.
        local items = diagnostics_for(buf)
        if #items > 0 then
          local diags = buffer_ref(root, buf)
          diags.kind = "diagnostics"
          diags.items = items
          tr:send(diags)
        end
        sent = sent + 1
      end
    end
  end
  return sent
end

function M.stop(root)
  if groups[root] then
    vim.api.nvim_del_augroup_by_id(groups[root])
    groups[root] = nil
  end
end

-- Answer an engine lsp_request. The engine has no language server; the editor does.
-- vim.lsp.buf_request_all is asynchronous and calls back with every client's answer.
local METHODS = {
  references = "textDocument/references",
  definition = "textDocument/definition",
  document_symbols = "textDocument/documentSymbol",
  hover = "textDocument/hover",
}

function M.answer_lsp(root, req)
  local tr = transport.for_workspace(root)
  local method = METHODS[req.method]
  local function reply(status, items)
    tr:send({ kind = "lsp_result", request_id = req.request_id, method = req.method,
              status = status, items = items or {} })
  end
  if not method then
    return reply("unsupported")
  end
  local abs = root .. "/" .. req.path
  local buf = vim.fn.bufnr(abs)
  if buf == -1 then
    buf = vim.fn.bufadd(abs)
    vim.fn.bufload(buf)
  end
  if #vim.lsp.get_clients({ bufnr = buf }) == 0 then
    return reply("no_client")
  end
  local line, col = util.from_contract_pos(req.line or 1, req.col or 1)
  local params = {
    textDocument = { uri = vim.uri_from_bufnr(buf) },
    position = { line = line, character = col },
    context = req.method == "references" and { includeDeclaration = false } or nil,
  }
  vim.lsp.buf_request_all(buf, method, params, function(results)
    local items = {}
    for _, res in pairs(results or {}) do
      for _, loc in ipairs(res.result or {}) do
        local uri = loc.uri or loc.targetUri
        local range = loc.range or loc.targetSelectionRange
        if uri and range then
          local l, c = util.to_contract_pos(range.start.line, range.start.character)
          table.insert(items, { path = util.relative(root, vim.uri_to_fname(uri)), line = l, col = c })
        end
      end
    end
    reply("ok", items)
  end)
end

return M
