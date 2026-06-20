"""
app/watchlist.py — 워치리스트 로더 (data/watchlist.csv 단일 출처)

CSV 컬럼: symbol,name,country,market,original_sector,current_category,is_active
- 코드에서 종목을 추가/삭제하지 않는다. CSV가 유일한 출처.
- 한국 종목만 거래대금 기준 분류 대상. 해외/M7은 분류 고정.
"""
from __future__ import annotations
import csv
import os

_CSV = os.path.join(os.path.dirname(__file__), "..", "data", "watchlist.csv")


def load_all() -> list[dict]:
    rows = []
    with open(_CSV, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if str(r.get("is_active", "TRUE")).upper() != "FALSE":
                rows.append(r)
    return rows


def all_korean_stocks() -> list[dict]:
    """한국 종목만 (code,name,market,origin_sector)."""
    out = []
    for r in load_all():
        if r["country"] == "KR":
            out.append({
                "code": r["symbol"], "name": r["name"], "market": r["market"],
                "origin_sector": r["original_sector"], "origin_sub": "",
                "tier": "",
            })
    return out


def all_global_stocks() -> list[dict]:
    """해외 종목(거래대금 미적용, 분류 고정). M7 포함."""
    out = []
    for r in load_all():
        if r["country"] != "KR":
            out.append({
                "ticker": r["symbol"], "name": r["name"], "market": r["market"],
                "cc": r["country"], "origin_sector": r["original_sector"],
            })
    return out


if __name__ == "__main__":
    kr = all_korean_stocks()
    g = all_global_stocks()
    print(f"한국 {len(kr)} / 해외·M7 {len(g)}")
