"""Detect tasks from a (previous_sha, new_sha) pair of a Python file, using tree-sitter.

Phase 1: function signature changes. Also emits the ordinary non-actions:
  unknown_intent  -> file does not parse cleanly (mid-edit); nothing to do yet
  noop            -> parsed fine, no signature changed
"""
from __future__ import annotations

from dataclasses import dataclass, field

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser

PY = Language(tspython.language())
_parser = Parser(PY)


@dataclass(frozen=True)
class Param:
    name: str
    kind: str           # pos | kwonly | varargs | varkw
    has_default: bool

    def render(self) -> str:
        pre = {"varargs": "*", "varkw": "**"}.get(self.kind, "")
        return f"{pre}{self.name}{'=…' if self.has_default else ''}"


@dataclass(frozen=True)
class Signature:
    qualname: str        # Class.method or function
    name: str
    params: tuple[Param, ...]
    line: int            # 1-based def line
    is_method: bool

    def render(self) -> str:
        return f"{self.qualname}({', '.join(p.render() for p in self.params)})"

    @property
    def positional(self) -> list[Param]:
        return [p for p in self.params if p.kind == "pos"]

    @property
    def required(self) -> list[Param]:
        return [p for p in self.params if p.kind in ("pos", "kwonly") and not p.has_default]

    @property
    def has_varargs(self) -> bool:
        return any(p.kind == "varargs" for p in self.params)

    @property
    def has_varkw(self) -> bool:
        return any(p.kind == "varkw" for p in self.params)


def parse(src: bytes):
    return _parser.parse(src)


def _text(n: Node, src: bytes) -> str:
    return src[n.start_byte:n.end_byte].decode(errors="replace")


def _params(node: Node, src: bytes) -> tuple[Param, ...]:
    out: list[Param] = []
    kwonly = False
    for c in node.named_children:
        t = c.type
        if t == "identifier":
            out.append(Param(_text(c, src), "kwonly" if kwonly else "pos", False))
        elif t == "typed_parameter":
            ident = next((x for x in c.children if x.type == "identifier"), None)
            if ident is None:  # *args: T / **kw: T inside typed_parameter
                splat = c.children[0]
                nm = _text(splat.named_children[0], src) if splat.named_children else _text(splat, src)
                kind = "varargs" if splat.type == "list_splat_pattern" else "varkw"
                out.append(Param(nm, kind, False))
                kwonly = kwonly or kind == "varargs"
            else:
                out.append(Param(_text(ident, src), "kwonly" if kwonly else "pos", False))
        elif t in ("default_parameter", "typed_default_parameter"):
            nm = c.child_by_field_name("name")
            out.append(Param(_text(nm, src), "kwonly" if kwonly else "pos", True))
        elif t == "list_splat_pattern":
            out.append(Param(_text(c.named_children[0], src) if c.named_children else "args", "varargs", False))
            kwonly = True
        elif t == "dictionary_splat_pattern":
            out.append(Param(_text(c.named_children[0], src) if c.named_children else "kwargs", "varkw", False))
        elif t == "keyword_separator":
            kwonly = True
        elif t == "positional_separator":
            pass
    return tuple(out)


def signatures(src: bytes) -> tuple[list[Signature], bool]:
    """All function/method signatures in a module. Returns (sigs, has_error)."""
    tree = parse(src)
    sigs: list[Signature] = []

    def walk(n: Node, scope: list[str]):
        for c in n.children:
            if c.type == "class_definition":
                nm = c.child_by_field_name("name")
                body = c.child_by_field_name("body")
                if nm is not None and body is not None:
                    walk(body, scope + [_text(nm, src)])
            elif c.type == "function_definition":
                nm = c.child_by_field_name("name")
                ps = c.child_by_field_name("parameters")
                if nm is not None and ps is not None:
                    name = _text(nm, src)
                    sigs.append(Signature(".".join(scope + [name]), name, _params(ps, src),
                                          c.start_point[0] + 1, bool(scope)))
                body = c.child_by_field_name("body")
                if body is not None:
                    walk(body, scope + [_text(nm, src)] if nm is not None else scope)
            elif c.type == "decorated_definition":
                walk(c, scope)
            elif c.type in ("block", "if_statement", "try_statement", "else_clause", "except_clause"):
                walk(c, scope)

    walk(tree.root_node, [])
    return sigs, tree.root_node.has_error


@dataclass
class Task:
    kind: str                     # signature_change | removed_function | new_function | unknown_intent | noop
    path: str
    based_on: dict[str, str]      # path -> sha this task is judged against (staleness key)
    qualname: str | None = None
    old: Signature | None = None
    new: Signature | None = None
    detail: str = ""
    seq: int | None = None
    id: str = field(default="")

    def __post_init__(self):
        if not self.id:
            self.id = f"{self.kind}:{self.path}:{self.qualname or '-'}:{self.based_on.get(self.path, '')}"


def detect(path: str, old_src: bytes | None, new_src: bytes, sha: str, seq: int | None = None) -> list[Task]:
    based = {path: sha}
    new_sigs, err = signatures(new_src)
    if err:
        return [Task("unknown_intent", path, based, detail="file does not parse cleanly (mid-edit?)", seq=seq)]
    if old_src is None:
        return [Task("noop", path, based, detail="first observation of file; nothing to compare", seq=seq)]
    old_sigs, old_err = signatures(old_src)
    if old_err:
        # previous state was mid-edit; compare only names we can, never invent a change
        return [Task("noop", path, based, detail="previous snapshot did not parse; baseline reset", seq=seq)]
    old_by = {s.qualname: s for s in old_sigs}
    new_by = {s.qualname: s for s in new_sigs}
    tasks: list[Task] = []
    for q, ns in new_by.items():
        os_ = old_by.get(q)
        if os_ is None:
            tasks.append(Task("new_function", path, based, q, None, ns, seq=seq))
        elif os_.params != ns.params:
            tasks.append(Task("signature_change", path, based, q, os_, ns,
                              detail=f"{os_.render()} -> {ns.render()}", seq=seq))
    for q, os_ in old_by.items():
        if q not in new_by:
            tasks.append(Task("removed_function", path, based, q, os_, None, detail=f"removed {os_.render()}", seq=seq))
    if not tasks:
        tasks.append(Task("noop", path, based, detail="no signature changed", seq=seq))
    return tasks
