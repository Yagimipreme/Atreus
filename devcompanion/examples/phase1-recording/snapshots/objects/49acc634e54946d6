import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from calc import add, scale, Ledger


def test_add():
    assert add(1, 2) == 3


def test_scale():
    assert scale([1, 2], 2) == [2, 4]


def test_ledger():
    assert Ledger().post(5, "x") == 1
