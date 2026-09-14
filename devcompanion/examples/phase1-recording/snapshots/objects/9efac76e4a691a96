from calc import Ledger, add, scale


def total(xs):
    t = 0
    for x in xs:
        t = add(t, x)
    return t


def doubled(xs):
    return scale(xs, 2)


def book(amounts):
    ledger = Ledger()
    for a in amounts:
        ledger.post(a, memo="auto")
    return ledger
