"""Find call sites of a function across the repo and judge each against the new signature.

Tools: `rg` for candidates (respects .gitignore), tree-sitter for the actual call node.
Every judgement carries the sha of the file it was read from (staleness key).
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from tree_sitter import Node

from ..schedule.detect import Signature, parse
from ..snapshot.store import sha_of


@dataclass
class CallSite:
    path: str
    line: int
    col: int
    text: str
    verdict: str        # breaks | ok | unsure
    reason: str
    file_sha: str


def _text(n: Node, src: bytes) -> str:
    return src[n.start_byte:n.end_byte].decode(errors="replace")


def candidates(root: Path, name: str) -> list[Path]:
    try:
        out = subprocess.run(
            ["rg", "-l", "--type", "py", "-e", rf"\b{name}\s*\(", str(root)],
            capture_output=True, text=True, timeout=20,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    return [Path(l) for l in out.stdout.splitlines() if l.strip()]


def judge(sig: Signature, n_pos: int, kws: list[str], has_splat: bool, via_attr: bool) -> tuple[str, str]:
    params = list(sig.params)
    if sig.is_method and via_attr and params and params[0].kind == "pos":
        params = params[1:]  # self/cls bound
    pos = [p for p in params if p.kind == "pos"]
    names = {p.name for p in params if p.kind in ("pos", "kwonly")}
    varargs = any(p.kind == "varargs" for p in params)
    varkw = any(p.kind == "varkw" for p in params)
    if has_splat:
        return "unsure", "call uses *args/**kwargs unpacking"
    if n_pos > len(pos) and not varargs:
        return "breaks", f"{n_pos} positional args, signature takes {len(pos)}"
    unknown = [k for k in kws if k not in names]
    if unknown and not varkw:
        return "breaks", f"unknown keyword {unknown[0]!r}"
    covered = {p.name for p in pos[:n_pos]} | set(kws)
    missing = [p.name for p in params if p.kind in ("pos", "kwonly") and not p.has_default and p.name not in covered]
    if missing:
        return "breaks", f"missing required {missing[0]!r}"
    return "ok", "arguments fit the new signature"


def find_calls(path: Path, src: bytes, sig: Signature) -> list[CallSite]:
    tree = parse(src)
    fsha = sha_of(src)
    out: list[CallSite] = []

    def walk(n: Node):
        if n.type == "call":
            fn = n.child_by_field_name("function")
            args = n.child_by_field_name("arguments")
            if fn is not None and args is not None:
                via_attr = fn.type == "attribute"
                callee = _text(fn.child_by_field_name("attribute"), src) if via_attr else _text(fn, src)
                if callee == sig.name:
                    n_pos, kws, splat = 0, [], False
                    for a in args.named_children:
                        if a.type == "keyword_argument":
                            kws.append(_text(a.child_by_field_name("name"), src))
                        elif a.type in ("list_splat", "dictionary_splat"):
                            splat = True
                        elif a.type != "comment":
                            n_pos += 1
                    v, why = judge(sig, n_pos, kws, splat, via_attr)
                    out.append(CallSite(str(path), n.start_point[0] + 1, n.start_point[1] + 1,
                                        _text(n, src).splitlines()[0][:120], v, why, fsha))
        for c in n.children:
            walk(c)

    walk(tree.root_node)
    return out


def investigate(candidate_paths: list[str], sig: Signature, defining_path: str, read: callable,
                is_stale: callable) -> list[CallSite] | None:
    """Return call sites, or None if the investigation was abandoned because input went stale.
    Paths are root-relative; `read` resolves them (disk when live, snapshot when replaying)."""
    sites: list[CallSite] = []
    for rel in sorted(candidate_paths):
        if is_stale():
            return None
        src = read(rel)
        if src is None:
            continue
        for cs in find_calls(Path(rel), src, sig):
            if rel == defining_path and cs.line == sig.line:
                continue  # the def line itself
            sites.append(cs)
    return sites
