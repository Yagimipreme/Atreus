# Canonical text

Status: 2026-09-14. Normative for both halves.

The engine hashes files as they sit on disk. The adapter hashes buffers that have never been
written. Those two hashes have to be equal the instant the developer saves, because everything
downstream — which revision a claim rests on, whether a finding is stale, whether the analysed
content is the content in front of the developer — is a hash comparison.

So the canonical bytes of a buffer are defined as **exactly the bytes Neovim would write for
it**:

    lines joined by the buffer's 'fileformat' separator
      unix -> \n      dos -> \r\n      mac -> \r
    plus one trailing separator when 'eol' is set

Nothing else. No trimming, no normalising of line endings, no stripping of a trailing blank
line. `fileformat` and `eol` are buffer options read at the boundary, never guessed.

The empty buffer looks like an exception and is not. A buffer holding a single empty line
writes one separator with `eol` and nothing at all with `noeol` — which is also why a 0-byte
file reads back as one empty line with `noeol`. An earlier version of this document did
special-case it, and the fixture check below is what caught that.

## Hash

    sha256(canonical bytes), hex, first 16 characters

The same digest and width `snapshot/store.py` uses for file content, so an editor hash and an
engine hash are directly comparable and a saved buffer's `text_sha` *is* the file's
`content_sha`.

16 hex characters is 64 bits. This is an equality check on content the developer produced, not
a defence against a chosen-prefix attack, and a collision would surface as one stale finding.

## Implementations

| Side | Function |
|---|---|
| Lua | `util.canonical_text(buf)`, `util.text_sha(text)` |
| Python | `canon.canonical(lines, fileformat, eol)`, `canon.sha(bytes)`, `canon.text_sha(text)` |

The adapter sends the canonical text itself in `text`, already joined, so the engine only ever
re-hashes what arrived. It never reconstructs the bytes from lines, and it never trusts the
declared `text_sha`: it recomputes, and reports a mismatch in `engine.json`'s `last_error`
while still using the bytes that actually arrived.

## Fixtures

`tests/fixtures/text-canon.json` holds one case per shape that has ever been ambiguous:
empty buffer with and without `eol`, no trailing newline, blank last line, DOS endings,
tabs, UTF-8 identifiers, internal blank lines.

Both checks run the same file:

- `tests/test_canon.py` — the Python side, fast.
- `scripts/check-workflow.py` — loads each case into a real headless Neovim, hashes it with
  the adapter's own function, `:write`s it, and asserts that the fixture hash, the Python
  hash, the Lua hash and the hash of the file on disk are all one value.

Regenerating the fixtures to make a failure go away defeats the purpose. If a case is wrong,
establish what Neovim actually writes first.
