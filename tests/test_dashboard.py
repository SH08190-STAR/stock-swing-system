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


# ── 매매기록 연동 줄 (진입가 표시 버그 회귀) ────────────────
def test_trade_line_kr_entered_price_not_symbol():
    m = _dash()
    r = {"status": "entered", "symbol": "320000", "market_group": "KR",
         "entry1": 12500, "record_date": "2026-07-06"}
    line = m.format_trade_line(r, "KRW", 11830)
    assert line.startswith("진입 7/6")
    assert "12,500원" in line                 # 실제 진입가
    assert "320000" not in line               # 종목코드가 가격 자리에 나오면 안 됨
    assert "현재가 대비 +5.7%" in line


def test_trade_line_us_entered():
    m = _dash()
    r = {"status": "entered", "symbol": "NVDA", "entry1": 190, "record_date": "2026-07-09"}
    line = m.format_trade_line(r, "USD", 200.0)
    assert "$190.00" in line and "현재가 대비 -5.0%" in line


def test_trade_line_entry_fallbacks():
    m = _dash()
    # entry1 없음 → entry2
    r = {"status": "entered", "symbol": "005490", "entry2": 300000, "record_date": "2026-07-01"}
    assert "300,000원" in m.format_trade_line(r, "KRW", None)
    # 전부 없음 → '진입가 —', symbol을 가격 대신 쓰지 않음
    r2 = {"status": "entered", "symbol": "005490", "record_date": "2026-07-01"}
    line2 = m.format_trade_line(r2, "KRW", 100000)
    assert "진입가 —" in line2 and "005490" not in line2


def test_trade_line_waiting_and_tpin():
    m = _dash()
    w = {"status": "waiting", "entry1": 10500, "record_date": "2026-07-21"}
    lw = m.format_trade_line(w, "KRW", 11830)
    assert lw.startswith("대기중 7/21") and "진입 예정 10,500원" in lw
    w2 = {"status": "waiting", "record_date": "2026-07-21"}
    assert "진입 예정 —" in m.format_trade_line(w2, "KRW", None)
    t = {"status": "tp_in", "tp1": 15000, "record_date": "2026-07-09"}
    assert "다음 목표 15,000원" in m.format_trade_line(t, "KRW", 13800)
    t2 = {"status": "tp_in", "realized_tp1_profit": 1, "stop": 9800, "record_date": "2026-07-09"}
    assert "손절가 9,800원" in m.format_trade_line(t2, "KRW", None)
    t3 = {"status": "tp_in", "record_date": "2026-07-09"}
    assert "목표가 —" in m.format_trade_line(t3, "KRW", None)
    # 날짜 이상값 → 날짜만 생략, 예외 없음
    t4 = {"status": "entered", "entry1": 100, "record_date": None}
    assert m.format_trade_line(t4, "USD", None).startswith("진입 ·") or \
           m.format_trade_line(t4, "USD", None).startswith("진입")


# ── 검색 헬퍼 ───────────────────────────────────────────────
def test_stock_match_rank_variants():
    m = _dash()
    nvda = {"code": "NVDA", "name": "NVIDIA"}
    assert m.stock_match_rank(nvda, "nvda") == 0            # 대소문자 무시
    assert m.stock_match_rank(nvda, "NVDA") == 0
    assert m.stock_match_rank({"code": "440110", "name": "파두"}, "파두") == 1
    assert m.stock_match_rank({"code": "005930", "name": "삼성전자"}, "5930") == 0   # zfill
    assert m.stock_match_rank({"code": "028260", "name": "삼성물산"}, "삼성") is not None  # 부분
    assert m.stock_match_rank(nvda, "파두") is None
    assert m.stock_match_rank({"code": None, "name": None}, "x") is None   # None 안전


def test_filter_stocks_by_query():
    m = _dash()
    import pandas as pd
    df = pd.DataFrame([{"code": "NVDA", "name": "NVIDIA"}, {"code": "440110", "name": "파두"}])
    assert len(m.filter_stocks_by_query(df, "")) == 2               # 빈 검색어 → 원본
    assert list(m.filter_stocks_by_query(df, "파두")["code"]) == ["440110"]
    assert len(m.filter_stocks_by_query(df, "twlo")) == 0           # subset 밖 미포함


def test_trade_matches_query_fields():
    m = _dash()
    r = {"symbol": "EOSE", "leverage_symbol": "EOSU", "memo": "지열 스윙", "status": "waiting",
         "record_date": "2026-07-08", "market_group": "US"}
    assert m.trade_matches_query(r, "eose")                 # symbol
    assert m.trade_matches_query(r, "EOSU")                 # leverage
    assert m.trade_matches_query(r, "지열")                  # memo
    assert m.trade_matches_query(r, "2026-07-08")           # 날짜
    assert m.trade_matches_query(r, "")                     # 빈 검색어 → True
    assert not m.trade_matches_query(r, "nvda")
    kr = {"symbol": "440110", "market_group": "KR", "memo": None}
    assert m.trade_matches_query(kr, "파두", {"440110": "파두"})   # 종목명(name map)
    assert m.trade_matches_query(kr, "5930", {"440110": "파두"}) is False  # zfill 미스매치 안전


# ── 손익 표시색 (폴리시 — 수익 빨강/손실 파랑/0 중립, 비숫자 None) ──
def test_pnl_color():
    m = _dash()
    assert m.pnl_color(1500) == "#f04452"        # 수익 → 빨강
    assert m.pnl_color(-300) == "#3182f6"        # 손실 → 파랑
    assert m.pnl_color(0) == "#333d4b"           # 0 → 중립
    assert m.pnl_color(None) is None             # 값 없음 → 색 미적용
    assert m.pnl_color("abc") is None            # 비숫자 → 색 미적용
    assert m.pnl_color(float("nan")) is None     # NaN → 색 미적용


# ── 가격 출처·기준일 표시줄 ─────────────────────────────────
def test_quote_basis_line_formats():
    m = _dash()
    assert m.quote_basis_line("Supabase", "2026-07-10") == \
        "가격 기준 2026-07-10 종가 · Supabase"
    assert m.quote_basis_line("FDR", "2026-07-12") == "가격 기준 2026-07-12 · FDR"
    assert m.quote_basis_line(None, None) is None
    assert "기준일 미상" in m.quote_basis_line("FDR", None)


def test_pair_basis_line_consistent_and_inconsistent():
    m = _dash()
    good = m.make_quote_pair(m.make_snapshot("TEM", 61.5, "Supabase", "2026-07-10"),
                             m.make_snapshot("TEMT", 24.4, "Supabase", "2026-07-10"))
    assert m.pair_basis_line(good) == "가격 기준 2026-07-10 종가 · Supabase"
    bad = m.make_quote_pair(m.make_snapshot("TEM", 61.5, "Supabase", "2026-07-10"),
                            m.make_snapshot("TEMT", 24.4, "FDR", "2026-07-11"))
    line = m.pair_basis_line(bad)
    assert "불일치" in line and "Supabase" in line and "FDR" in line
    assert m.pair_basis_line({"base": None, "leverage": None,
                              "is_consistent": False, "reason": "가격 조회 실패"}) is None
    assert m.pair_basis_line(None) is None


# ── 내비게이션 헬퍼 (UI 1단계 — pills/radio 폴백) ─────────────
def test_select_pills_empty_and_default():
    m = _dash()
    # 빈 옵션 → None (예외 없음)
    assert m.select_pills("메뉴A", [], key=None) is None
    # 위젯 컨텍스트 없는 bare 모드에서는 기본 선택값이 그대로 반환된다
    assert m.select_pills("메뉴B", ["a", "b"], default_idx=1, key=None) == "b"
    # default_idx 범위 밖 → 0으로 보정 (예외 없음)
    assert m.select_pills("메뉴C", ["a", "b"], default_idx=9, key=None) == "a"
