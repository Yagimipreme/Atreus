def add(a, b):
    return a + b


def scale(values, factor=1):
    return [v * factor for v in values]


class Ledger:
    def __init__(self):
        self.entries = []

    def post(self, amount, memo):
        self.entries.append((amount, memo))
        return len(self.entries)
