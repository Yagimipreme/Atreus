"""A call counts only where the function can be reached from. Found in the panel: a removed helper
`add`, nested in one function, turned 32 unrelated `add(...)` calls into breaking call sites."""
from devcompanion.engine import Engine
from devcompanion.investigate import callers
from devcompanion.observe.events import Event
from devcompanion.schedule.detect import signatures


def sig_of(src: str, qualname: str):
    return next(s for s in signatures(src.encode())[0] if s.qualname == qualname)


def sites(sig, defining: str, files: dict[str, str]) -> list[tuple[str, int, str]]:
    found = callers.investigate(list(files), sig, defining, lambda rel: files[rel].encode(), lambda: False)
    return sorted((s.path, s.line, s.verdict) for s in found)


def test_a_nested_helper_is_called_only_inside_its_enclosing_function():
    corpus = ("def packet(base):\n    def add(rel):\n        return rel\n    add('a', 1)\n    return base\n\n\n"
              "def other():\n    found = set()\n    found.add(1)\n    add(1, 2)\n")
    add = sig_of(corpus, "packet.add")
    assert add.local and not add.is_method and add.enclosing == "packet"
    files = {
        "scripts/corpus.py": corpus,
        "docs/workflow/generate.py": "def add(root, tag):\n    pass\n\nadd('r', 'bpmn:process')\n",
        "src/engine.py": "found = set()\nfound.add('x')\n",
    }
    assert sites(add, "scripts/corpus.py", files) == [("scripts/corpus.py", 4, "breaks")]


def test_a_module_function_is_reached_through_its_imports_and_nothing_else():
    calc = "def add(a, b, carry):\n    return a + b + carry\n\n\nadd(1, 2)\n"
    files = {
        "pkg/calc.py": calc,
        "pkg/client.py": "from .calc import add\nadd(1, 2)\n",
        "app/alias.py": "from pkg.calc import add as plus\nplus(1, 2, 3)\n",
        "app/module.py": "import pkg.calc as c\nc.add(1, 2)\n",
        "app/package.py": "from pkg import calc\ncalc.add(1, 2, 3)\n",
        "app/star.py": "from pkg.calc import *\nadd(1)\n",
        "app/unrelated.py": "def add(a, b):\n    pass\n\nadd(1, 2)\nitems = set()\nitems.add(1)\n",
        "app/other_calc.py": "from other.calc import add\nadd(1, 2)\n",
    }
    assert sites(sig_of(calc, "add"), "pkg/calc.py", files) == [
        ("app/alias.py", 2, "ok"), ("app/module.py", 2, "breaks"), ("app/package.py", 2, "ok"),
        ("app/star.py", 2, "breaks"), ("pkg/calc.py", 5, "breaks"), ("pkg/client.py", 2, "breaks"),
    ]


def test_a_method_is_certain_through_self_or_its_class_and_unsure_through_anything_else():
    cart = "class Cart:\n    def add(self, sku, qty):\n        pass\n\n    def refill(self):\n        self.add('x')\n"
    files = {
        "pkg/cart.py": cart,
        "app/shop.py": ("from pkg.cart import Cart\n\n\ndef buy(cart, seen):\n    cart.add('x')\n    seen.add('y', 2)\n"
                        "    Cart.add(cart, 'x', 1)\n"),
        "app/unrelated.py": "items = set()\nitems.add(1)\n",
    }
    found = callers.investigate(list(files), sig_of(cart, "Cart.add"), "pkg/cart.py",
                                lambda rel: files[rel].encode(), lambda: False)
    assert sorted((s.path, s.line, s.verdict, s.certain) for s in found) == [
        ("app/shop.py", 5, "unsure", False),   # missing qty, if `cart` is a Cart
        ("app/shop.py", 6, "ok", False),       # fits either way
        ("app/shop.py", 7, "breaks", True),    # the class itself; unbound call, flagged conservatively
        ("pkg/cart.py", 6, "breaks", True),
    ]


def test_removing_a_nested_helper_names_only_the_calls_that_can_reach_it(tmp_path):
    before = "def packet(base):\n    def add(rel):\n        return rel\n    add('a')\n    return base\n"
    after = "def packet(base):\n    add('a')\n    return base\n"
    (tmp_path / "corpus.py").write_text(before)
    (tmp_path / "generate.py").write_text("def add(root, tag):\n    pass\n\nadd('r', 'x')\n")
    (tmp_path / "engine.py").write_text("found = set()\nfound.add('x')\n")
    eng = Engine(tmp_path, run_tests=False, log=lambda _: None)
    for name in ("corpus.py", "generate.py", "engine.py"):
        eng.handle_event(Event(kind="buffer_saved", path=name))
    eng.sched.drain(wait=False)

    (tmp_path / "corpus.py").write_text(after)
    eng.handle_event(Event(kind="buffer_saved", path="corpus.py"))
    eng.sched.drain(wait=False)
    record = eng.evid.state["removed_function:corpus.py:packet.add"]
    assert [(l["path"], l["line"], l["verdict"]) for l in record["locations"]] == [("corpus.py", 2, "breaks")]
