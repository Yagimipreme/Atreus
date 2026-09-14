# Cases for :Chatty explain. A case runs from its `# %%` line to the next. `# expect:` is shown to
# you beside the reply and never sent; `# path:` is the file name the model is told.

# %% late-binding
# path: src/app/events.py
# expect: every handler logs the loop's final `i` and `name` -- the lambdas look them up when called, not when defined
import logging

log = logging.getLogger(__name__)


def make_handlers(names):
    handlers = {}
    for i, name in enumerate(names):
        handlers[name] = lambda event: log.info("%d %s %s", i, name, event)
    return handlers


# %% bisect-bucket
# path: src/app/sizes.py
# expect: labels a number by range; a boundary goes to the upper bucket (10 is "medium", 0 is "small"), negatives are "tiny"
import bisect

BOUNDS = [0, 10, 100, 1000]
LABELS = ["tiny", "small", "medium", "large", "huge"]


def size_label(n):
    return LABELS[bisect.bisect_right(BOUNDS, n)]


# %% sentinel-default
# path: src/app/settings.py
# expect: `_MISSING` tells "no default given" apart from `default=None`; without a default the bare `raise` re-raises the KeyError
_MISSING = object()


def get_setting(settings, key, default=_MISSING):
    try:
        return settings[key]
    except KeyError:
        if default is _MISSING:
            raise
        return default


# %% generator-exhausted
# path: src/app/report.py
# expect: `rows` is a generator the count consumes, so `widths` is always empty and the second value is always 0
def load_rows(path):
    with open(path) as fh:
        for line in fh:
            if line.strip():
                yield line.rstrip("\n").split(",")


def summarize(path):
    rows = load_rows(path)
    count = sum(1 for _ in rows)
    widths = [len(r) for r in rows]
    return count, max(widths, default=0)


# %% eq-without-hash
# path: src/app/geometry.py
# expect: defining `__eq__` without `__hash__` makes `Point` unhashable, so `p in seen` / `seen.add(p)` raise TypeError
class Point:
    def __init__(self, x, y):
        self.x, self.y = x, y

    def __eq__(self, other):
        return isinstance(other, Point) and (self.x, self.y) == (other.x, other.y)


seen = set()


def first_visit(p):
    if p in seen:
        return False
    seen.add(p)
    return True


# %% full-jitter
# path: src/app/retry.py
# expect: exponential backoff with full jitter -- the ceiling doubles from 0.5, each delay is random below it; with the defaults the ceiling tops out at 16, so `cap` never applies
import random


def backoff_delays(base=0.5, cap=30.0, attempts=6):
    delay = base
    for _ in range(attempts):
        yield random.uniform(0, delay)
        delay = min(cap, delay * 2)
