"""The canonical form is a contract between two languages, so it is pinned by fixtures rather
than by assertions written next to the implementation. scripts/check-workflow.py runs the same
fixtures through a real Neovim and a real :write; this file is the fast half."""
import json
from pathlib import Path

import pytest

from devcompanion import canon

FIXTURES = json.loads((Path(__file__).parent / "fixtures/text-canon.json").read_text())["cases"]


@pytest.mark.parametrize("case", FIXTURES, ids=lambda c: c["name"])
def test_canonical_matches_fixture(case):
    body = canon.canonical(case["lines"], case["fileformat"], case["eol"])
    assert body == bytes.fromhex(case["bytes_hex"])
    assert canon.sha(body) == case["sha"]
    assert canon.text_sha(body.decode()) == case["sha"]


@pytest.mark.parametrize("case", FIXTURES, ids=lambda c: c["name"])
def test_lines_round_trip(case):
    body = canon.canonical(case["lines"], case["fileformat"], case["eol"])
    assert canon.lines_of(body, case["fileformat"]) == case["lines"]


def test_sha_matches_the_snapshot_store():
    """The two halves of the engine must not drift apart either."""
    from devcompanion.snapshot.store import sha_of
    assert canon.sha(b"def add(a, b):\n") == sha_of(b"def add(a, b):\n")


def test_empty_buffer_depends_on_eol():
    """The case that looked like a special case and is not: an empty buffer is one empty line,
    which writes one separator, or nothing when the buffer has no trailing newline."""
    assert canon.canonical([""], "unix", eol=True) == b"\n"
    assert canon.canonical([""], "unix", eol=False) == b""
