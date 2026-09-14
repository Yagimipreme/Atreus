"""Find call sites of a function across the repo and judge each against the new signature.

Tools: `rg` for candidate files (respects .gitignore), tree-sitter for the call nodes, and each
file's own imports for whether a call can reach the function at all. A name alone proves nothing:
a removed helper `add` nested in one function made every `add(...)` in the workspace -- another
module's `add`, `found.add(rel)` on a set -- a "breaking" call site. So a call counts only where
the function is reachable:

  nested function   inside its enclosing function, in its own file
  module function   in its own file by bare name; elsewhere through `from m import f [as g]`,
                    `from m import *`, `import m [as x]` then `x.f()`, or `from pkg import m`,
                    relative imports resolved against the importing file's package
  method            `self.m()` / `cls.m()` / `Class.m()`; any other receiver only in a file that
                    defines or imports the class, and then as `unsure`: its type is not known here

Every judgement carries the sha of the file it was read from (staleness key).
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from tree_sitter import Node

from ..schedule.detect import Signature, parse, signatures
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
    certain: bool = True  # False: a method call whose receiver may be some other type


@dataclass(frozen=True)
class Reach:
    """Which calls in one file can reach the function."""
    bare: frozenset[str] = frozenset()    # names it is called by directly
    via: frozenset[str] = frozenset()     # receivers that certainly are its module or class
    any_receiver: bool = False            # a method: other receivers count, as unsure
    lines: tuple[int, int] | None = None  # only calls within these lines (a nested function's scope)


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


# ---------------------------------------------------------------- reachability

def module_parts(rel: str) -> list[str]:
    parts = rel.removesuffix(".py").split("/")
    return parts[:-1] if parts and parts[-1] == "__init__" else parts


def imports(src: bytes) -> list[tuple[str, int, str | None, str | None]]:
    """(module, level, name, alias) per imported thing, including imports inside functions:
    `import a.b as x` -> ("a.b", 0, None, "x"); `from ..a import b as y` -> ("a", 2, "b", "y");
    `from . import m` -> ("", 1, "m", None); a wildcard's name is "*"."""
    out: list[tuple[str, int, str | None, str | None]] = []

    def aliased(c: Node) -> tuple[str, str | None]:
        if c.type == "aliased_import":
            return _text(c.child_by_field_name("name"), src), _text(c.child_by_field_name("alias"), src)
        return _text(c, src), None

    def walk(n: Node) -> None:
        if n.type == "import_statement":
            for c in n.children_by_field_name("name"):
                module, alias = aliased(c)
                out.append((module, 0, None, alias))
        elif n.type == "import_from_statement":
            mod = n.child_by_field_name("module_name")
            if mod is None:
                return
            level, module = 0, _text(mod, src)
            if mod.type == "relative_import":
                prefix = next((x for x in mod.children if x.type == "import_prefix"), None)
                dotted = next((x for x in mod.children if x.type == "dotted_name"), None)
                level = len(_text(prefix, src)) if prefix is not None else 0
                module = _text(dotted, src) if dotted is not None else ""
            if any(c.type == "wildcard_import" for c in n.children):
                out.append((module, level, "*", None))
            for c in n.children_by_field_name("name"):
                name, alias = aliased(c)
                out.append((module, level, name, alias))
        else:
            for c in n.children:
                walk(c)

    walk(parse(src).root_node)
    return out


def _resolve(module: str, level: int, importer: str) -> list[str] | None:
    names = module.split(".") if module else []
    if level == 0:
        return names
    base = importer.split("/")[:-1]
    if level - 1 > len(base):
        return None
    return base[:len(base) - (level - 1)] + names


def _is(target: list[str], candidate: list[str] | None, level: int) -> bool:
    """Whether an import names the defining module. A relative import resolves exactly; an absolute
    one matches the end of the module's path, since the import root (src/, a sys.path entry) is not
    known here."""
    if not candidate:
        return False
    if level:
        return candidate == target
    return len(candidate) <= len(target) and target[-len(candidate):] == candidate


def reach(sig: Signature, defining: str, rel: str, src: bytes) -> Reach | None:
    """How the function can be called from `rel`, or None when it cannot be reached from there."""
    method_via = {"self", "cls", sig.owner} if sig.is_method else set()
    if sig.local:
        if rel != defining:
            return None
        outer = next((s for s in signatures(src)[0] if s.qualname == sig.enclosing), None)
        if outer is None:
            return None
        return Reach(frozenset() if sig.is_method else frozenset({sig.name}), frozenset(method_via),
                     sig.is_method, (outer.line, outer.end_line))
    target = module_parts(defining)
    subject = sig.owner if sig.is_method else sig.name
    bare: set[str] = set()
    via: set[str] = set(method_via) if rel == defining else set()
    if rel == defining and not sig.is_method:
        bare.add(sig.name)
    for module, level, name, alias in imports(src):
        full = _resolve(module, level, rel)
        suffix = f".{sig.owner}" if sig.is_method else ""
        if name is None:                                     # import m [as x]
            if _is(target, full, level):
                via.add((alias or module) + suffix)
        elif name == "*":
            if _is(target, full, level):
                (via if sig.is_method else bare).add(subject)
        elif _is(target, full, level):                       # from m import f / Class
            if name == subject:
                (via if sig.is_method else bare).add(alias or name)
        elif full is not None and _is(target, full + [name], level):   # from pkg import m
            via.add((alias or name) + suffix)
    if not bare and not via:
        return None
    return Reach(frozenset(bare), frozenset(via), sig.is_method)


# ---------------------------------------------------------------- judging

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


def find_calls(path: Path, src: bytes, sig: Signature, reach: Reach | None = None) -> list[CallSite]:
    """Calls to `sig` in one file. Without a `reach`, every call by that name counts."""
    tree = parse(src)
    fsha = sha_of(src)
    out: list[CallSite] = []

    def walk(n: Node):
        if n.type == "call":
            fn = n.child_by_field_name("function")
            args = n.child_by_field_name("arguments")
            line = n.start_point[0] + 1
            in_scope = reach is None or reach.lines is None or reach.lines[0] <= line <= reach.lines[1]
            if fn is not None and args is not None and in_scope:
                via_attr = fn.type == "attribute"
                certain = True
                if via_attr:
                    attr, receiver = fn.child_by_field_name("attribute"), fn.child_by_field_name("object")
                    matched = attr is not None and _text(attr, src) == sig.name
                    if matched and reach is not None:
                        certain = receiver is not None and _text(receiver, src) in reach.via
                        matched = certain or reach.any_receiver
                else:
                    matched = _text(fn, src) == sig.name if reach is None else _text(fn, src) in reach.bare
                if matched:
                    n_pos, kws, splat = 0, [], False
                    for a in args.named_children:
                        if a.type == "keyword_argument":
                            kws.append(_text(a.child_by_field_name("name"), src))
                        elif a.type in ("list_splat", "dictionary_splat"):
                            splat = True
                        elif a.type != "comment":
                            n_pos += 1
                    v, why = judge(sig, n_pos, kws, splat, via_attr)
                    if not certain and v == "breaks":
                        v, why = "unsure", f"{why}, if the receiver is a {sig.owner}"
                    out.append(CallSite(str(path), line, n.start_point[1] + 1,
                                        _text(n, src).splitlines()[0][:120], v, why, fsha, certain))
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
        where = reach(sig, defining_path, rel, src)
        if where is None:
            continue
        # The def line itself -- but only while the function is still defined there. A removed
        # function's signature carries its old line, which in the new source can hold a real call.
        def_line = sig.line if rel == defining_path and any(
            s.qualname == sig.qualname and s.line == sig.line for s in signatures(src)[0]) else None
        for cs in find_calls(Path(rel), src, sig, where):
            if cs.line != def_line:
                sites.append(cs)
    return sites
