# Documentation for the code in view

Status: design, 2026-09-14. Not built. The user asked for both halves: surfacing the documentation
that exists, and writing documentation that does not.

## Two functions

| | Surface existing documentation | Write documentation |
|---|---|---|
| What | the docs for what the code in view uses | a docstring or prose for a selection |
| Kind | retrieval: passages with a source | generation: explaining code |
| Mark | ✓ fact, cited | ◇ advice |
| `local-only` | yes | unavailable — needs a reasoning model |
| `hybrid` | adds remote documentation search, on request | flagship |
| Routing key | `pulled.docs.surface` | `pulled.docs.write` |

Writing documentation is explaining code, which the local model does unreliably
([evaluations/chatty-functions.md](evaluations/chatty-functions.md)), so it goes to the flagship. A
proposed docstring is an edit and goes through [edit-actions.md](edit-actions.md).

Surfacing never rewords a passage. A model may rank passages, but it never paraphrases them:
deterministic tools discover facts, and a model only compresses or connects them
([model-routing.md](model-routing.md)).

## Where library documentation comes from

Four sources, cheapest and most exact first. **No local copy of whole documentation sites is
needed for the common case.**

1. **The project's own environment — no copy.**
   - The docstrings and signatures of the exact installed versions are already on disk in the
     project's virtual environment.
   - The editor's language server returns them as hover. The adapter already answers an engine
     `lsp_request` for `hover`, `definition`, `references` and `document_symbols` with an
     `lsp_result` (`nvim/lua/companion/collect.lua`). The engine records results but never sends
     a request yet.
   - Alternatively, the engine reads them statically from the installed source. **Never by
     importing**: importing a module runs it.
   - Covers the API reference; misses guides and narrative documentation.
2. **Project docs and knowledge bases through QMD — exists.** The repository's own docs and KBs,
   already indexed.
3. **A local copy of one library's full docs, when docstrings are not enough.**
   - DevDocs publishes pre-generated docsets: normalised HTML partials, an index and offline JSON,
     fetched with `thor docs:download <docset>`. Zeal/Dash docsets are similar.
   - Converted to Markdown, they index as a QMD collection, searched by keyword only, as
     `repo-pyerp-external` already is for vendor docs.
   - Per library, on request. Such a copy drifts from the installed version.
4. **A web API — `hybrid` only, pulled only.**
   - **Context7**:
     - `GET /v2/libs/search` finds a library, and `GET /v2/context` returns reranked snippets for a
       library id.
     - Needs an API key; lists versions.
   - **Read the Docs search**:
     - `GET https://app.readthedocs.org/api/v3/search/?q=project:<slug>/<version> <terms>`.
     - No key for public projects; results link to page sections.
   - **What leaves the machine** is a library name, symbol names and a query, not code. That is
     still content: it names the dependencies and what the developer is looking at. So it is a
     remote profile under the same machine grant as any other ([configuration.md](configuration.md)),
     and never runs passively.

Recommended order: 1, then 2 — both local, so `local-only` gets the whole function. Add 3 for a
library whose docstrings are thin. Offer 4 as a named remote profile.

## Shape

- **Input**:
  - the names the code in view uses, resolved to their package through its imports (the engine
    already resolves names for caller analysis)
  - a question, if the developer typed one
- **Output**: a few cited passages, one line each until opened. For example:
  `Session.mount · requests 2.32 · docstring`, or `retries · urllib3 docs · devdocs`.
- **Freshness**: a passage names the version it came from; one from a docset older than the
  installed version says so.

## Open

Which source to build first. Recommended: the project's environment, through the language server.

## Sources

- Context7 API guide: https://context7.com/docs/api-guide
- DevDocs README: https://github.com/freeCodeCamp/devdocs
- Read the Docs search API: https://docs.readthedocs.com/platform/stable/server-side-search/api.html
- Conversation 2026-09-14
