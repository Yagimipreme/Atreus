# Cases for :Chatty grill. Each has one planted weakness; the first question should go at it.
# `clamp` is a control: inventing a problem there is unusable. `# expect:` is never sent.

# %% check-then-insert
# path: src/app/users.py
# expect: races -- two requests can both see no user and insert twice (is there a unique constraint?); email case/whitespace not normalised
def ensure_user(db, email):
    if db.find_user(email) is None:
        db.insert_user(email)
    return db.find_user(email)


# %% swallowed-errors
# path: src/app/sync.py
# expect: every failure is skipped silently -- which errors should stop the loop (auth, network) and how does the caller learn which orders failed?
def sync_orders(client, orders):
    synced = 0
    for order in orders:
        try:
            client.push(order)
            synced += 1
        except Exception:
            continue
    return synced


# %% cache-forever
# path: src/app/prices.py
# expect: the module-level cache never expires or invalidates (stale prices), grows without bound, and ignores which `fetch` filled it
_prices = {}


def price_for(sku, fetch):
    if sku not in _prices:
        _prices[sku] = fetch(sku)
    return _prices[sku]


# %% split-bill
# path: src/app/billing.py
# expect: the shares need not add up to `total` (100 / 3) -- where does the remainder go? float for money; `people` of 0
def split_bill(total, people):
    share = round(total / people, 2)
    return [share] * people


# %% naive-now
# path: src/app/tokens.py
# expect: `datetime.now()` is local and naive -- what timezone is `created_at` stored in? an aware `created_at` raises TypeError; DST
from datetime import datetime, timedelta


def is_expired(created_at, ttl_hours=24):
    return datetime.now() - created_at > timedelta(hours=ttl_hours)


# %% clamp
# path: src/app/numbers.py
# expect: control, nothing planted -- "little to challenge" is good; a NaN question is fair; invented problems are unusable
def clamp(value: float, low: float, high: float) -> float:
    """Return value limited to the closed interval [low, high]."""
    if low > high:
        raise ValueError(f"low {low} is greater than high {high}")
    return max(low, min(value, high))
