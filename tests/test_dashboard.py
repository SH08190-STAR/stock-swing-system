"""
tests/test_dashboard.py — 대시보드 52주 고점 표시 헬퍼 검증 (네트워크/실DB 없음).
"""
import os
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _dash():
    p = os.path.join(ROOT, "dashboard", "app.py")
    spec = importlib.util.spec_from_file_location("dash_for_52w_test", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ── 고점 대비 이격률 계산 ───────────────────────────────────
def test_calc_gap_from_high_basic():
    m = _dash()
    assert m.calc_gap_from_high(88000, 100000) == -12.0
    assert m.calc_gap_from_high(105000, 100000) == 5.0


def test_calc_gap_from_high_safe_none():
    m = _dash()
    assert m.calc_gap_from_high(None, 100000) is None      # 현재가 없음
    assert m.calc_gap_from_high(88000, None) is None       # 고점 없음
    assert m.calc_gap_from_high(88000, 0) is None          # 고점 0
    assert m.calc_gap_from_high(0, 100000) is None         # 현재가 0
    assert m.calc_gap_from_high(88000, float("nan")) is None  # NaN


# ── 표시 라인 포맷 ──────────────────────────────────────────
def test_format_52w_line_kr():
    m = _dash()
    row = {"close": 88000, "high_52w": 100000, "country": "KR", "market": "KOSPI"}
    assert m.format_52w_high_line(row) == "52주 고점 100,000원 · 고점 대비 -12.0%"


def test_format_52w_line_us():
    m = _dash()
    row = {"close": 188, "high_52w": 200, "country": "US", "market": "NASDAQ"}
    assert m.format_52w_high_line(row) == "52주 고점 $200.00 · 고점 대비 -6.0%"


def test_format_52w_line_positive_gap():
    m = _dash()
    row = {"close": 105000, "high_52w": 100000, "country": "KR", "market": "KOSPI"}
    assert m.format_52w_high_line(row) == "52주 고점 100,000원 · 고점 대비 +5.0%"


def test_format_52w_line_missing_high():
    m = _dash()
    for h in (None, 0, float("nan")):
        row = {"close": 88000, "high_52w": h, "country": "KR", "market": "KOSPI"}
        assert m.format_52w_high_line(row) == "52주 고점 —"


def test_format_52w_line_high_only_no_gap():
    m = _dash()
    # 현재가 없으면 이격률 생략, 고점 가격만 표시(예외 없음)
    row = {"close": None, "high_52w": 200, "country": "US", "market": "NASDAQ"}
    assert m.format_52w_high_line(row) == "52주 고점 $200.00"
