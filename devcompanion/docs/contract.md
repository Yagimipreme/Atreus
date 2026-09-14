# Adapter ↔ engine contract v2

Status: implemented, 2026-09-14. This is the only thing the Lua side and the Python side
share. Both must remain correct when the other is absent: Neovim with no engine running shows
a panel that says so; the engine with no editor attached still processes file events.

Everything crossing the boundary is a single-line JSON object. Field names are `snake_case`.

**Unknown fields are preserved, not ignored.** v1 said they were ignored, and the Python
decoder took that literally: it rebuilt only its own field list, so `text`, `dirty`, `session`
and the rest of the editor's state were dropped on intake and unsaved buffers were unusable.
v2 keeps what it does not recognise (`Event.extra`), so a newer adapter talking to an older
engine loses nothing.

## Changes from v1

| Change | Why |
|---|---|
| `schema_version` is `2` | the intake rule above is a real schema change, not an addition |
| `text` is canonical bytes, defined in [text-canon.md](text-canon.md) | an editor hash and an engine hash of the same buffer must be equal |
| `fileformat`, `eol` on content events | they are what make `text` reproducible as bytes |
| `source` on every event | the log is read by people; "which producer" is the first question |
| new `session_end` event | an editor that quits takes its unsaved buffers with it |
| findings carry `revision` | whether a claim rests on a saved file or an unsaved buffer |
| `engine.json` carries `revisions`, `dirty_buffers` | so the editor can tell whether the engine has caught up with the buffer |

## 0. Transport (deliberately dumb)

    <workspace>/.companion/
      inbox.jsonl      adapter appends  -> engine tails      (events)
      findings.jsonl   engine rewrites  -> adapter reads     (current findings, full state)
      engine.json      engine writes    -> adapter reads     (liveness, version, counters)
      outbox.jsonl     engine appends   -> adapter tails     (LSP requests; not yet produced)

Append-only files plus rewritten state files. No socket, no daemon protocol, no RPC. A socket
replaces `transport.lua` and one engine module later without touching collect or the panel.

Rewrite rule for `findings.jsonl` and `engine.json`: write `<name>.tmp`, then rename over the
target. Readers therefore always see a complete file. The adapter reloads on mtime change and
never polls faster than its configured `poll_ms`.

The engine also writes `board.md`, `quickfix.txt`, `events.jsonl`, `evidence.jsonl`,
`state.json`, `view.json` and `snapshots/`. Those are its own records, not part of this
contract; the adapter reads none of them.

## 1. Events (adapter -> engine)

Common envelope on every event:

| field | type | meaning |
|---|---|---|
| `schema_version` | int | `2` |
| `seq` | int | monotonic per Neovim session, never reused |
| `ts` | float | unix seconds |
| `kind` | string | see below |
| `source` | string | producer: `nvim`, `fswatch`, `cli`, `replay`, `git` |
| `workspace` | string | absolute path to workspace root |
| `session` | string | id unique per Neovim instance, so two editors never interleave; opaque to the engine — compared, never parsed |

The engine assigns its own `seq` on intake and keeps the adapter's as `editor_seq`, so the two
counters never have to agree.

### `buffer_changed`

Debounced text change. Carries the text itself, because the file on disk is stale while editing.

    {"schema_version":2,"seq":12,"ts":1788945000.4,"kind":"buffer_changed","source":"nvim",
     "workspace":"/p","session":"a1b2","path":"src/config.py","doc_version":47,"bufnr":3,
     "text_sha":"9f2a…","text":"…full buffer…","language":"python","dirty":true,
     "fileformat":"unix","eol":true}

`text` is **canonical text** — see [text-canon.md](text-canon.md). `text_sha` is its hash, and
the engine recomputes rather than trusting it. `fileformat` and `eol` travel with it because
they are what define those bytes.

`doc_version` is `vim.b.changedtick`. `dirty` is the field the whole feature turns on: while it
is true the content exists only in the buffer, and the engine analyses it as an *overlay* over
the file rather than as the file.

The engine does not put `text` in its own event log — the bytes go to the snapshot store and
the logged event keeps `content_sha` and `content_origin` — so an event log plus a snapshot
store remains a complete replayable input without growing by a buffer per keystroke pause.

### `buffer_saved`

Same fields as `buffer_changed`, plus `dirty:false`. Emitted on `BufWritePost`.

A save that changes no bytes is still news: the same content moved from a buffer onto disk,
where tools that read the working tree can finally see it. The engine re-runs those tools and
retires the overlay.

### `session_end`

    {…,"kind":"session_end"}

Emitted on `VimLeavePre`, and the one event written synchronously — on `VimLeavePre` the event
loop stops before any async write would complete. Unsaved buffers die with the editor, so the
engine drops that session's overlays, falls each path back to the file, and re-judges it.
Without this the engine would keep reporting content that exists nowhere.

### `cursor`

Weak attention evidence. No text.

    {…,"kind":"cursor","path":"src/config.py","doc_version":47,"line":88,"col":12}

### `diagnostics`

The adapter owns this: Neovim already holds the LSP clients. Sent on `DiagnosticChanged`,
debounced, for the changed buffer only.

    {…,"kind":"diagnostics","path":"src/config.py","doc_version":47,
     "items":[{"line":88,"col":12,"end_line":88,"end_col":24,"severity":"error",
               "code":"E0308","source":"rust-analyzer","message":"mismatched types"}]}

`severity` is one of `error warn info hint`. Positions are 1-based lines, 1-based columns,
converted from Neovim's 0-based API at the boundary. Empty `items` means "all clear now" and
must be sent, because clearing is information.

The engine stores these and republishes the errors among its findings, so one pane holds the
whole picture. Warnings are not republished: they are already in the sign column.

### `lsp_result`

The engine cannot talk to language servers. It asks through the adapter and gets this back.

    {…,"kind":"lsp_result","request_id":"r-31","method":"references",
     "status":"ok","items":[{"path":"src/main.py","line":14,"col":5}]}

`status` is `ok | unsupported | timeout | no_client | error`. All four non-ok cases are ordinary.

### `goal`

Optional short statement typed by the developer. Free text, never required.

    {…,"kind":"goal","text":"make configuration paths portable"}

### `dismiss`

    {…,"kind":"dismiss","finding_id":"f-77","scope":"finding"}

`scope` is `finding` (this one) or `kind_at_location` (this kind of finding, here, until the
evidence changes).

### `request`

Explicit developer ask, bypasses the passive cadence.

    {…,"kind":"request","what":"explain_diagnostic","path":"src/config.py","line":88}

## 2. Requests (engine -> adapter)

The engine needs the editor for two things: LSP queries and buffer text it does not have.
Written to `outbox.jsonl`, tailed by the adapter, answered with an `lsp_result` event.

    {"schema_version":1,"kind":"lsp_request","request_id":"r-31","method":"references",
     "path":"src/config.py","line":12,"col":5,"timeout_ms":3000}

`method` in v1: `references`, `definition`, `document_symbols`, `hover`. The adapter refuses
anything else with `status:"unsupported"` rather than guessing.

## 3. Findings (engine -> adapter)

One JSON object per line, the file is the complete current set. Order is engine-chosen; the
adapter renders in file order.

| field | type | meaning |
|---|---|---|
| `schema_version` | int | `1` |
| `id` | string | stable across re-derivations of the same claim |
| `kind` | string | `diagnostic_context`, `caller_affected`, `doc_passage`, `test_result`, `action`, `roadmap_note` |
| `surface` | string | `errors`, `callers`, `docs`, `roadmap` — which surface renders it |
| `title` | string | one line, no trailing period |
| `basis` | string | `observed`, `inferred`, `predicted`, `outdated` |
| `location` | object | `{path,line,col}` or `{path}` for file scope; required unless `scope` given |
| `scope` | array | paths or symbols, when the finding is not a single point |
| `consequence` | string | what it means for the developer, one sentence |
| `evidence` | array | `{kind,ref,detail}` — `kind` is `diagnostic`, `lsp`, `test`, `snapshot`, `doc`, `model` |
| `action` | object\|null | `{label, id}` — the adapter offers it, the engine performs it |
| `depends_on` | object | `{path: content_sha}`; when any differs from the current buffer, the finding is stale |
| `revision` | object | `{path: "disk"\|"editor"}` — whether each input was the saved file or an unsaved buffer |
| `saved_revision_only` | bool | present on `test_result`: this evidence cannot speak for unsaved buffers |
| `snapshot_id` | string | the immutable input this was derived from |
| `created_ts` | float | |

`revision` is how a reader tells "your saved code is broken" from "what you are typing right
now would break". The panel marks the second `[buffer]`.

Example:

    {"schema_version":1,"id":"f-77","kind":"caller_affected","surface":"callers",
     "title":"config_path() now returns Path, caller still concatenates a str",
     "basis":"observed","location":{"path":"src/main.py","line":14,"col":5},
     "consequence":"This call site will raise TypeError at runtime",
     "evidence":[{"kind":"lsp","ref":"r-31","detail":"references on config_path"},
                 {"kind":"diagnostic","ref":"d-88","detail":"basedpyright: no overload"}],
     "action":null,"depends_on":{"src/config.py":"9f2a…","src/main.py":"1c4e…"},
     "snapshot_id":"snap-42","created_ts":1788945002.1}

### Rendering rules the adapter must honour

- Nothing opens, focuses, or steals the cursor. Surfaces open only on a keymap or command.
- A finding whose `depends_on` no longer matches the live buffer renders dimmed as stale, or is
  hidden, per user setting. It is never silently shown as current. The adapter recomputes this
  itself from the live buffer rather than trusting the published file, because the buffer moves
  on between engine writes.
- `basis` is always visible: observed and inferred must be distinguishable at a glance.
- `action` is offered, never applied. Applying sends a `request` and the engine re-checks freshness.

## 4. Engine liveness

`engine.json`, rewritten whenever it changes:

    {"schema_version":1,"pid":12345,"started_ts":…,"heartbeat_ts":…,"version":"0.2.0",
     "state":"idle","workspace":"/p","session":"a1b2","last_event_seq":418,"pending_tasks":0,
     "dirty_buffers":["src/config.py"],
     "revisions":{"src/config.py":{"sha":"9f2a…","origin":"editor","dirty":true,"doc_version":47}},
     "findings":3,"model":{"name":"qwen3-coder:30b","backend":"ollama","status":"ready"},
     "context":{"backend":"qmd","status":"disabled","passages":0},"last_error":null,
     "intake":{"offset":40213,"resumed_at":40213,"skipped_known":0,"malformed":0,"resets":0}}

| field | type | meaning |
|---|---|---|
| `intake` | object | `{offset, resumed_at, skipped_known, malformed, resets}` — the durable read position over `inbox.jsonl`; see [intake-watermark.md](intake-watermark.md) |

`state` is `idle | working | paused`. `model.status` is `ready | loading | unavailable | disabled`.
An unavailable model is not an error state for the engine.

`revisions` is the analysis manifest: the revision the engine actually read for each path it
has an opinion about. The editor compares its buffer's canonical hash against it to answer the
only question a status line really has — *is this talking about the code in front of me?*

`intake` is present with all-zero counters (and no offset) when there is no inbox to read —
`companion ingest` and `companion replay` never see one. `resumed_at` and `skipped_known` are
what turn "the engine restarted" into "the engine resumed": a nonzero `skipped_known` after a
restart is the engine having re-read old bytes and correctly declined events it already took.

Every field is present even when its subsystem is off, so the panel never has to render a gap
where an answer belongs. Note that JSON `null` decodes to `vim.NIL` in Lua, not `nil`: the
adapter normalises on decode (`util.decode_json`).

## 5. Invariants

1. The adapter never blocks the UI thread on the engine. Every read is async or from a cached table.
2. The engine never writes to developer-authored files. Only `.companion/` and its own workspaces.
3. Every finding carries evidence with a checkable ref, or it is not emitted.
4. Sequence numbers are monotonic per session; the engine tracks a watermark
   (`docs/intake-watermark.md`) and never re-derives evidence for an event it has already
   taken. `events.jsonl`, the raw append-only log, is the one place this is at-least-once
   rather than exactly-once: an event whose handling finished but whose watermark commit did
   not (a crash in that narrow window) is re-delivered on restart and appended a second time.
   `handle_event` returns early once it sees the same content already the latest snapshot of
   that path, so nothing downstream re-runs — a duplicate log line, not duplicate work.
5. Both sides tolerate the other restarting at any point. State lives in files, not in memory.
6. The engine never claims an unsaved buffer is the file, and never presents evidence from a
   tool that could not see the buffer without saying so.
