"""
tests/test_watchlist.py — 워치리스트 CSV 무결성
"""
import re
from collections import Counter
from app import watchlist as W


def test_counts():
    kr = W.all_korean_stocks()
    g = W.all_global_stocks()
    assert len(kr) == 89, f"한국 종목 89 기대, 실제 {len(kr)}"
    # 해외 79 + M7 8 = 87
    assert len(g) == 87, f"해외+M7 87 기대, 실제 {len(g)}"


def test_no_duplicate_symbols():
    rows = W.load_all()
    syms = [r["symbol"] for r in rows]
    dups = [s for s, c in Counter(syms).items() if c > 1]
    assert not dups, f"중복 symbol: {dups}"


def test_korean_market_valid():
    for s in W.all_korean_stocks():
        assert s["market"] in ("KOSPI", "KOSDAQ"), f"이상 시장: {s}"


def test_korean_code_format():
    for s in W.all_korean_stocks():
        assert re.fullmatch(r"\d{6}", s["code"]), f"비표준 코드: {s['code']}"
