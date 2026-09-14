# Cases for :Chatty plan. `# goal:` is sent as the goal; `# expect:` is never sent.
# `cart-already-rejects` is a control: the goal is already met.

# %% timeout-per-call
# path: src/app/client.py
# goal: let callers pass a timeout per request instead of the fixed 10 seconds
# expect: `timeout` parameter on `get` defaulting to 10 (behaviour kept), threaded through `get_json`; `health` needs no change; a test that the value reaches `urlopen`
import json
import urllib.request


class Client:
    def __init__(self, base_url):
        self.base_url = base_url

    def get(self, path):
        with urllib.request.urlopen(self.base_url + path, timeout=10) as r:
            return r.read()

    def get_json(self, path):
        return json.loads(self.get(path))


def health(client):
    return client.get_json("/health")


# %% retry-requests
# path: src/app/transport.py
# goal: retry failed requests up to three times
# expect: flags first that retrying POST and other non-idempotent methods can repeat side effects; retry only connection errors / 5xx, not 4xx; backoff; test
def send(session, method, url, body=None):
    response = session.request(method, url, data=body)
    response.raise_for_status()
    return response


# %% inject-clock
# path: src/app/session.py
# goal: make is_expired testable without sleeping
# expect: inject a clock (`now` callable, defaulting to UTC now) into `Session`; use it in both `__init__` and `is_expired`; tests pass a fake clock
from datetime import datetime, timedelta, timezone


class Session:
    def __init__(self, ttl=timedelta(hours=1)):
        self.created = datetime.now(timezone.utc)
        self.ttl = ttl

    def is_expired(self):
        return datetime.now(timezone.utc) - self.created > self.ttl


# %% cart-already-rejects
# path: src/app/cart.py
# goal: reject negative quantities when adding to the cart
# expect: control -- says first that `add` already raises for `qty <= 0`; at most suggests a test
class Cart:
    def __init__(self):
        self.items = {}

    def add(self, sku, qty=1):
        if qty <= 0:
            raise ValueError("quantity must be positive")
        self.items[sku] = self.items.get(sku, 0) + qty


# %% split-parse-store
# path: src/app/importer.py
# goal: split parse_and_store so parsing can be tested without a database
# expect: extract a pure `parse_records(text)` (keeping the line-number errors); `parse_and_store` becomes parse then insert, so its callers don't change; unit tests for parsing with no db
def parse_and_store(db, text):
    records = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split(";")
        if len(parts) != 3:
            raise ValueError(f"line {lineno}: expected 3 fields")
        name, qty, price = parts
        records.append((name.strip(), int(qty), float(price)))
    for record in records:
        db.execute("INSERT INTO items VALUES (?, ?, ?)", record)
    db.commit()
    return len(records)


# %% rename-keep-alias
# path: src/app/users.py
# goal: rename fetch_user to get_user everywhere, keeping old imports working for one release
# expect: rename the definition; update `profile_page` and `admin_view`; keep `fetch_user` as a deprecated alias (warning); search other modules for imports; a test for both names
def fetch_user(db, user_id):
    return db.get("users", user_id)


def profile_page(db, user_id, render):
    user = fetch_user(db, user_id)
    return render("profile.html", user=user)


def admin_view(db, ids):
    return [fetch_user(db, i) for i in ids]
