"""
tests/test_classifier.py — 분류/계산 인수 테스트 (외부 소스 없이 동작)
합성 일봉은 로직 검증 전용이며 실제 시세가 아니다.
"""
import datetime as dt
import pandas as pd
import pytest

from app import classifier as C
from app import config

END = dt.date(2026, 6, 19)
DATES = pd.bdate_range(END - pd.Timedelta(days=250), END)[-120:]


def _collected(value_per_day, close=10000, days=None):
    idx = DATES if days is None else DATES[-days:]
    df = pd.DataFrame(
        {"close": [close] * len(idx), "volume": [1000] * len(idx),
         "value": [value_per_day] * len(idx)},
        index=idx,
    )
    return {"code": "TEST", "name": "T", "market": "KOSPI", "ohlcv": df,
            "status": "ok", "reason": "", "origin_sector": "x",
            "origin_sub": "y", "tier": "growth"}


def test_threshold_constant():
    assert config.SWING_THRESHOLD_KRW == 100_000_000_000


def test_a1_below_is_swing():
    assert C.classify_one(_collected(800 * 10**8), END)["classification"] == "swing"


def test_a2_exact_is_swing():
    # 정확히 1,000억 → 이하 포함 → swing
    assert C.classify_one(_collected(1000 * 10**8), END)["classification"] == "swing"


def test_a3_above_is_sector():
    assert C.classify_one(_collected(1500 * 10**8), END)["classification"] == "sector"


def test_c3_halt_zero_excluded():
    c = _collected(800 * 10**8)
    col = c["ohlcv"].columns.get_loc("value")
    c["ohlcv"].iloc[-5:, col] = 0  # 거래정지 5일
    r = C.classify_one(c, END)
    assert r["used_days"] == 115  # 0원 제외


def test_c4_too_few_days_hold():
    r = C.classify_one(_collected(500 * 10**8, days=20), END)
    assert r["classification"] == "hold"


def test_c2_collect_fail_hold():
    r = C.classify_one(
        {"code": "X", "name": "x", "market": "KOSDAQ", "ohlcv": None,
         "status": "hold", "reason": "blocked"}, END)
    assert r["classification"] == "hold"


def test_b3_b4_b5_diff():
    prev = {"A": "sector", "B": "swing", "C": "sector", "D": "swing"}
    cur = [
        {"code": "A", "classification": "swing", "name": "A"},   # 신규 편입
        {"code": "B", "classification": "sector", "name": "B"},  # 섹터 복귀
        {"code": "C", "classification": "sector", "name": "C"},  # 변경 없음
        {"code": "D", "classification": "hold", "name": "D"},    # 보류 전환
    ]
    d = C.diff_classifications(prev, cur)
    assert [x["code"] for x in d["new_swing"]] == ["A"]
    assert [x["code"] for x in d["back_to_sector"]] == ["B"]
    assert [x["code"] for x in d["new_hold"]] == ["D"]
    # C(변경 없음)는 어디에도 없어야 함
    allc = sum(([x["code"] for x in v] for v in d.values()), [])
    assert "C" not in allc


def test_fmt_krw():
    assert "억" in C.fmt_krw(500 * 10**8)
