"""Canonical text: the one definition of "the bytes of this buffer", shared by both halves.

The engine hashes files it reads from disk; the adapter hashes buffers that were never
written. Those two hashes have to agree the instant the developer saves, or every freshness
check downstream is wrong. So the canonical form is defined as *exactly the bytes Neovim
would write for this buffer*:

    lines joined by the buffer's 'fileformat' separator,
    plus one trailing separator when 'eol' is set.

There is no special case for the empty buffer, though it looks like one: a buffer holding a
single empty line writes one separator with 'eol' and nothing without it, which is also why a
0-byte file reads back as one empty line with 'noeol'.

`fileformat` and `eol` are buffer options, not guesses; the adapter sends the joined result
and the engine only ever re-hashes it. `docs/text-canon.md` states the rule for both sides and
`tests/fixtures/text-canon.json` pins it with cases that a headless Neovim reproduces.
"""
from __future__ import annotations

import hashlib

SEPARATORS = {"unix": "\n", "dos": "\r\n", "mac": "\r"}
DEFAULT_FORMAT = "unix"


def separator(fileformat: str | None) -> str:
    return SEPARATORS.get(fileformat or DEFAULT_FORMAT, "\n")


def canonical(lines: list[str], fileformat: str | None = None, eol: bool = True) -> bytes:
    """The bytes a buffer of these lines becomes on disk."""
    if not lines:
        return b""
    sep = separator(fileformat)
    body = sep.join(lines)
    if eol:
        body += sep
    return body.encode("utf-8", errors="surrogateescape")


def sha(data: bytes) -> str:
    """Same digest and width the snapshot store uses, so shas are comparable everywhere."""
    return hashlib.sha256(data).hexdigest()[:16]


def text_sha(text: str) -> str:
    """Hash of canonical text that arrived over the wire already joined."""
    return sha(text.encode("utf-8", errors="surrogateescape"))


def lines_of(data: bytes, fileformat: str | None = None) -> list[str]:
    """Inverse of `canonical`, for fixtures and for showing engine-side content as a buffer."""
    sep = separator(fileformat)
    text = data.decode("utf-8", errors="surrogateescape")
    if text == "":
        return [""]
    if text.endswith(sep):
        text = text[: -len(sep)]
    return text.split(sep)
