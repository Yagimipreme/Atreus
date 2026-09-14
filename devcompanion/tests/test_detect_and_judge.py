from devcompanion.schedule.detect import detect, signatures
from devcompanion.investigate.callers import find_calls
from pathlib import Path


def sig(src, name):
    return next(s for s in signatures(src.encode())[0] if s.qualname == name)


def test_signature_kinds():
    s = sig("def f(a, b=1, *args, c, d=2, **kw): pass", "f")
    assert [p.kind for p in s.params] == ["pos", "pos", "varargs", "kwonly", "kwonly", "varkw"]
    assert [p.has_default for p in s.params] == [False, True, False, False, True, False]


def test_typed_and_method():
    src = "class C:\n    def m(self, x: int, y: str = 'a') -> None: pass\n"
    s = sig(src, "C.m")
    assert s.is_method and [p.name for p in s.params] == ["self", "x", "y"]


def test_detect_change_and_mid_edit():
    old, new = b"def f(a): pass\n", b"def f(a, b): pass\n"
    t = detect("x.py", old, new, "s1")
    assert t[0].kind == "signature_change" and "f(a) -> f(a, b)" in t[0].detail
    assert detect("x.py", old, b"def f(a\n", "s2")[0].kind == "unknown_intent"
    assert detect("x.py", None, new, "s3")[0].kind == "noop"
    assert detect("x.py", new, b"", "s4")[0].kind == "removed_function"


def test_judge_calls():
    s = sig("def f(a, b, *, c=0): pass", "f")
    src = b"f(1, 2)\nf(1)\nf(1, 2, 3)\nf(1, 2, c=1)\nf(1, 2, d=1)\nf(*xs)\n"
    v = [c.verdict for c in find_calls(Path("y.py"), src, s)]
    assert v == ["ok", "breaks", "breaks", "ok", "breaks", "unsure"]


def test_method_via_attribute_skips_self():
    s = sig("class C:\n    def m(self, x): pass\n", "C.m")
    src = b"obj.m(1)\nobj.m(1, 2)\nC.m(obj, 1)\n"
    v = [c.verdict for c in find_calls(Path("y.py"), src, s)]
    assert v == ["ok", "breaks", "breaks"]  # last: unbound call not modelled -> conservative flag
