"""
tests/test_trades.py — 매매 기록(trade_records) CRUD·가격 조회·레버리지 환산 검증.
실제 Supabase/네트워크 없이 mock으로 검증한다.
"""
import os
import sys
import importlib.util
import datetime as dt

from app import database as db

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _dash():
    """dashboard/app.py 모듈 로드(레버리지 계산 헬퍼 검증용)."""
    p = os.path.join(ROOT, "dashboard", "app.py")
    spec = importlib.util.spec_from_file_location("dash_for_test", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ── 레버리지 환산 공식 (2배 고정) ────────────────────────────
def test_lev_convert_formula():
    m = _dash()
    # etf 100, 본주 50 → 목표 55(+10%) → 100 × (1 + 0.1×2) = 120
    assert m.lev_convert(100.0, 50.0, 55.0) == 120.0
    # 손절 45(−10%) → 100 × (1 − 0.2) = 80
    assert m.lev_convert(100.0, 50.0, 45.0) == 80.0
    # 동일가 → 그대로
    assert m.lev_convert(100.0, 50.0, 50.0) == 100.0


# ── 완료 총손익 자동 계산 ───────────────────────────────────
def test_calc_total_pnl():
    m = _dash()
    assert m.calc_total_pnl(50000, 30000, 20000, 10000) == 90000
    assert m.calc_total_pnl(50000, None, None, -10000) == 40000   # 음수 손절 → abs
    assert m.calc_total_pnl(None, None, None, None) == 0
    assert m.calc_total_pnl(50000, 0, float("nan"), 0) == 50000   # NaN → 0


# ── 섹터 카드 연동: 표시가격/라벨 판정 ──────────────────────
def test_trade_display_price_waiting_entered():
    m = _dash()
    assert m.trade_display_price({"status": "waiting", "entry1": 175.0}) == ("대기중", 175.0)
    assert m.trade_display_price({"status": "waiting", "entry1": None, "entry2": 170.0}) == ("대기중", 170.0)
    assert m.trade_display_price({"status": "entered", "entry1": 188.2}) == ("진입", 188.2)
    assert m.trade_display_price({"status": "entered"}) == ("진입", None)
    assert m.trade_display_price({"status": "completed", "entry1": 1.0}) == (None, None)  # 완료 제외


def test_trade_display_price_tp_in():
    m = _dash()
    # tp1 미실현 → tp1
    r = {"status": "tp_in", "tp1": 210.0, "tp2": 230.0, "stop": 180.0}
    assert m.trade_display_price(r) == ("TP IN 다음 목표", 210.0)
    # tp1 실현, tp2 미실현 → tp2
    r["realized_tp1_profit"] = 50000
    assert m.trade_display_price(r) == ("TP IN 다음 목표", 230.0)
    # tp1/tp2 실현 → stop
    r["realized_tp2_profit"] = 30000
    assert m.trade_display_price(r) == ("TP IN 손절가", 180.0)
    # 전부 없음 → 가격 None
    assert m.trade_display_price({"status": "tp_in"}) == ("TP IN", None)


def test_gap_vs_current():
    m = _dash()
    assert m.gap_vs_current(110, 100) == 10.0
    assert m.gap_vs_current(90, 100) == -10.0
    assert m.gap_vs_current(None, 100) is None
    assert m.gap_vs_current(110, 0) is None


# ── realized_tp3 저장 경로(upsert pass-through) ─────────────
def test_completed_payload_includes_tp3(monkeypatch):
    calls = _patch(monkeypatch)
    db.upsert_trade_record({"id": "c1", "realized_tp1_profit": 50000,
                            "realized_tp2_profit": 30000, "realized_tp3_profit": 20000,
                            "realized_stop_loss": 10000, "realized_total_pnl": 90000})
    body = [c for c in calls if c[0] == "update"][0][2]
    assert body["realized_tp3_profit"] == 20000
    assert body["realized_total_pnl"] == 90000


def test_tp_in_payload_includes_tp1_tp2(monkeypatch):
    calls = _patch(monkeypatch)
    db.upsert_trade_record({"id": "t1", "realized_tp1_profit": 50000,
                            "realized_tp2_profit": 30000})
    body = [c for c in calls if c[0] == "update"][0][2]
    assert body["realized_tp1_profit"] == 50000
    assert body["realized_tp2_profit"] == 30000
    assert "realized_total_pnl" not in body     # TP IN은 총손익 미저장


def test_normalize_symbol_kr():
    m = _dash()
    assert m.normalize_symbol("5930", "KR") == "005930"      # 앞 0 보정
    assert m.normalize_symbol("005930", "KR") == "005930"    # 유지
    assert m.normalize_symbol(" 005930 ", "KR") == "005930"  # 공백 제거
    assert m.normalize_symbol("삼성전자", "KR") == "삼성전자"  # KR 이름은 그대로(보조조회용)
    assert m.normalize_symbol("", "KR") == ""


def test_normalize_symbol_us():
    m = _dash()
    assert m.normalize_symbol("nvda", "US") == "NVDA"
    assert m.normalize_symbol("NVDA", "US") == "NVDA"
    assert m.normalize_symbol(" nvdl ", "US") == "NVDL"


def test_trade_price_uses_zfilled_code(monkeypatch):
    """KR '5930' 입력 → latest_price('005930')로 조회되는지."""
    m = _dash()
    called = []
    monkeypatch.setattr(m, "latest_price", lambda s: called.append(s) or 71000.0)
    assert m.trade_price("5930", "KR") == 71000.0
    assert called == ["005930"]


def test_plain_target_stock_only_mode():
    """레버리지 ETF 없음: 환산가 = 본주 가격 그대로 + 수량 계산."""
    m = _dash()
    assert m._plain_target(190.0) == 190.0
    assert m._plain_target(None) is None
    assert m._plain_target(0) is None
    # 미장 본주: entry 190 / stop 180 / risk 70 → 주당 10 → 수량 7
    assert m.calc_position_qty(m._plain_target(190), m._plain_target(180), 70) == 7
    # 국장 본주: entry 80,000 / stop 75,000 / risk 200,000 → 주당 5,000 → 수량 40
    assert m.calc_position_qty(m._plain_target(80000), m._plain_target(75000), 200000) == 40


def test_kst_now_str_format():
    import re
    m = _dash()
    s = m.kst_now_str()
    # 'YYYY-MM-DD HH:mm KST' 형식
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} KST", s), s


def test_latest_price_cache_clear_safe():
    # 가격 새로고침 버튼이 호출하는 표적 캐시 초기화가 예외 없이 동작해야 함
    m = _dash()
    m.latest_price.clear()   # st.cache_data 함수의 clear() — bare mode에서도 안전


def test_clear_price_caches_pair_and_single_together():
    # 새로고침은 본주·ETF 쌍 캐시와 단일 캐시를 함께 초기화(예외 없음)
    m = _dash()
    m.clear_price_caches()


# ── 가격 쌍 일관성 (QuoteSnapshot / QuotePair) ───────────────
def test_pair_same_fdr_source_allowed():
    m = _dash()
    ok, reason = m.check_quote_pair(
        m.make_snapshot("PLTR", 126.79, "FDR", "2026-07-11"),
        m.make_snapshot("PLTU", 29.41, "FDR", "2026-07-11"))
    assert ok and reason == ""


def test_pair_base_fdr_etf_db_blocked():
    m = _dash()
    ok, reason = m.check_quote_pair(
        m.make_snapshot("PLTR", 126.79, "FDR", "2026-07-11"),
        m.make_snapshot("PLTU", 29.41, "Supabase", "2026-07-11"))
    assert not ok and reason == "가격 출처 불일치"


def test_pair_base_db_etf_fdr_blocked():
    m = _dash()
    ok, reason = m.check_quote_pair(
        m.make_snapshot("TEM", 61.50, "Supabase", "2026-07-10"),
        m.make_snapshot("TEMT", 24.40, "FDR", "2026-07-11"))
    assert not ok and reason == "가격 출처 불일치"


def test_pair_same_source_diff_date_blocked():
    m = _dash()
    ok, reason = m.check_quote_pair(
        m.make_snapshot("TEM", 61.50, "FDR", "2026-07-10"),
        m.make_snapshot("TEMT", 24.40, "FDR", "2026-07-11"))
    assert not ok and reason == "가격 기준일 불일치"


def test_pair_one_side_missing_blocked():
    m = _dash()
    snap = m.make_snapshot("TEMT", 24.40, "FDR", "2026-07-11")
    ok, reason = m.check_quote_pair(None, snap)
    assert not ok and reason == "본주 가격 없음"
    ok2, reason2 = m.check_quote_pair(snap, None)
    assert not ok2 and reason2 == "ETF 가격 없음"
    ok3, _ = m.check_quote_pair(m.make_snapshot("TEM", 0, "FDR", "2026-07-11"), snap)
    assert not ok3                                  # 0 가격은 무효


# ── 최신 공통 거래일 (DB fallback) ──────────────────────────
def test_latest_common_close_same_date():
    a = [{"date": "2026-07-11", "close": 100.0}]
    b = [{"date": "2026-07-11", "close": 25.5}]
    assert db.latest_common_close(a, b) == ("2026-07-11", 100.0, 25.5)


def test_latest_common_close_uses_common_not_each_latest():
    # 본주 최신 7/11, ETF 최신 7/10 → 공통 최신 7/10 사용(개별 최신 날짜 혼합 금지)
    a = [{"date": "2026-07-11", "close": 100.0}, {"date": "2026-07-10", "close": 99.0}]
    b = [{"date": "2026-07-10", "close": 25.0}, {"date": "2026-07-09", "close": 24.0}]
    assert db.latest_common_close(a, b) == ("2026-07-10", 99.0, 25.0)


def test_latest_common_close_none_when_disjoint():
    a = [{"date": "2026-07-11", "close": 100.0}]
    b = [{"date": "2026-06-01", "close": 1.0}]
    assert db.latest_common_close(a, b) is None     # 공통 거래일 없음 → 계산 금지
    assert db.latest_common_close(a, []) is None
    assert db.latest_common_close(None, None) is None


def test_db_pair_provider_common_date(monkeypatch):
    m = _dash()
    monkeypatch.setattr(m.db, "get_common_close_pair",
                        lambda a, b, lookback=10: ("2026-07-10", 61.50, 24.40))
    pair = m.DatabaseQuoteProvider().get_pair("TEM", "TEMT")
    assert pair["is_consistent"]
    assert pair["base"]["source"] == pair["leverage"]["source"] == "Supabase"
    assert pair["base"]["asof"] == pair["leverage"]["asof"] == "2026-07-10"


def test_db_pair_provider_none_when_no_common_date(monkeypatch):
    m = _dash()
    monkeypatch.setattr(m.db, "get_common_close_pair",
                        lambda a, b, lookback=10: None)
    assert m.DatabaseQuoteProvider().get_pair("TEM", "TEMT") is None


# ── 쌍 결정 우선순위 (FDR → DB, 혼합 금지) ──────────────────
def test_resolve_pair_falls_back_to_db_common_date(monkeypatch):
    m = _dash()
    # FDR은 본주만 성공 → DB 공통 거래일 쌍으로 폴백 (DB 본주+FDR ETF 혼합 금지)
    monkeypatch.setattr(
        m.FDRQuoteProvider, "get_single",
        lambda self, s: (m.make_snapshot(s, 126.79, "FDR", "2026-07-11")
                         if s == "PLTR" else None))
    monkeypatch.setattr(m.db, "get_common_close_pair",
                        lambda a, b, lookback=10: ("2026-07-10", 129.04, 29.41))
    pair = m.resolve_quote_pair("PLTR", "PLTU")
    assert pair["is_consistent"]
    assert pair["base"]["source"] == pair["leverage"]["source"] == "Supabase"


def test_resolve_pair_inconsistent_when_no_valid_pair(monkeypatch):
    m = _dash()
    # FDR 본주만 성공 + DB 공통 거래일 없음 → 불일치(계산 보류), 혼합하지 않음
    monkeypatch.setattr(
        m.FDRQuoteProvider, "get_single",
        lambda self, s: (m.make_snapshot(s, 126.79, "FDR", "2026-07-11")
                         if s == "PLTR" else None))
    monkeypatch.setattr(m.db, "get_common_close_pair",
                        lambda a, b, lookback=10: None)
    pair = m.resolve_quote_pair("PLTR", "PLTU")
    assert not pair["is_consistent"]
    assert pair["leverage"] is None                 # 다른 출처를 섞어 채우지 않음


def test_toss_provider_placeholder_not_implemented():
    m = _dash()
    t = m.TossQuoteProvider()
    assert t.get_single("PLTR") is None             # 실제 호출 미구현(구조만 준비)
    assert t.get_pair("PLTR", "PLTU") is None
    assert isinstance(m._QUOTE_PROVIDERS[0], m.TossQuoteProvider)  # 향후 1순위 자리


# ── _trade_calc: 쌍 일관성에 따른 계산 허용/보류 ─────────────
def test_trade_calc_allows_consistent_pair(monkeypatch):
    m = _dash()
    good = m.make_quote_pair(m.make_snapshot("PLTR", 50.0, "FDR", "2026-07-11"),
                             m.make_snapshot("PLTU", 100.0, "FDR", "2026-07-11"))
    monkeypatch.setattr(m, "quote_pair_cached", lambda b, l: good)
    r = {"market_group": "US", "symbol": "PLTR", "leverage_symbol": "PLTU",
         "entry1": 55.0, "stop": 45.0, "risk1": 400.0}
    c = m._trade_calc(r)
    assert c["consistent"] and c["is_lev"]
    assert c["e1_lev"] == 120.0 and c["stop_lev"] == 80.0   # 기존 환산 공식 유지
    assert c["qty1"] == 10                                   # 400 ÷ (120−80)
    assert "FDR" in c["basis"] and "2026-07-11" in c["basis"]


def test_trade_calc_blocks_on_inconsistent_pair(monkeypatch):
    m = _dash()
    bad = m.make_quote_pair(m.make_snapshot("PLTR", 129.04, "Supabase", "2026-07-10"),
                            m.make_snapshot("PLTU", 29.41, "FDR", "2026-07-11"))
    monkeypatch.setattr(m, "quote_pair_cached", lambda b, l: bad)
    r = {"market_group": "US", "symbol": "PLTR", "leverage_symbol": "PLTU",
         "entry1": 120.0, "stop": 110.0, "risk1": 100.0}
    c = m._trade_calc(r)
    assert not c["consistent"]
    assert c["e1_lev"] is None and c["stop_lev"] is None and c["qty1"] is None
    assert c["conv"](120.0) is None                 # 어떤 목표가도 환산하지 않음
    assert "불일치" in c["basis"]


def test_trade_calc_single_stock_keeps_behavior(monkeypatch):
    m = _dash()
    monkeypatch.setattr(m, "single_quote_cached",
                        lambda s: m.make_snapshot(s, 190.0, "Supabase", "2026-07-10"))
    r = {"market_group": "US", "symbol": "TEM", "leverage_symbol": None,
         "entry1": 190.0, "stop": 180.0, "risk1": 70.0}
    c = m._trade_calc(r)
    assert c["consistent"] and not c["is_lev"]
    assert c["base_now"] == 190.0 and c["trade_now"] == 190.0
    assert c["e1_lev"] == 190.0 and c["qty1"] == 7   # 본주 단독 기존 동작 유지
    assert "Supabase" in c["basis"]


def test_resolve_single_quote_db_first(monkeypatch):
    m = _dash()
    monkeypatch.setattr(m.db, "get_latest_quote",
                        lambda s: {"price": 71000.0, "asof": "2026-07-10"})
    s = m.resolve_single_quote("005930")
    assert s["source"] == "Supabase" and s["price"] == 71000.0
    assert s["asof"] == "2026-07-10"


def test_calc_position_qty_formula():
    m = _dash()
    # entry 환산 30, stop 환산 20 → 주당 리스크 10, risk 70 → 수량 7
    assert m.calc_position_qty(30.0, 20.0, 70.0) == 7


def test_calc_position_qty_normal_rounding():
    m = _dash()
    # 일반 반올림: 4.49→4, 4.50→5 (파이썬 기본 round의 은행가 방식 아님)
    assert m.calc_position_qty(30.0, 20.0, 44.9) == 4    # 4.49
    assert m.calc_position_qty(30.0, 20.0, 45.0) == 5    # 4.50 (round()라면 4가 됐을 값)
    assert m.calc_position_qty(30.0, 20.0, 55.0) == 6    # 5.50 → 6


def test_calc_position_qty_safe_none():
    m = _dash()
    assert m.calc_position_qty(None, 20.0, 70.0) is None      # entry 환산 없음
    assert m.calc_position_qty(30.0, None, 70.0) is None      # stop 환산 없음
    assert m.calc_position_qty(30.0, 20.0, None) is None      # risk 없음
    assert m.calc_position_qty(20.0, 20.0, 70.0) is None      # 주당 리스크 0
    assert m.calc_position_qty(15.0, 20.0, 70.0) is None      # 주당 리스크 음수
    assert m.calc_position_qty(30.0, 20.0, 0) is None         # risk 0
    assert m.calc_position_qty(30.0, 20.0, -5) is None        # risk 음수
    assert m.calc_position_qty(30.0, float("nan"), 70.0) is None  # NaN


def test_lev_convert_safe_none():
    m = _dash()
    assert m.lev_convert(None, 50.0, 55.0) is None      # ETF 현재가 없음
    assert m.lev_convert(100.0, None, 55.0) is None     # 본주 현재가 없음
    assert m.lev_convert(100.0, 50.0, None) is None     # 목표가 없음
    assert m.lev_convert(0, 50.0, 55.0) is None         # 0 가격
    assert m.lev_convert(100.0, -1.0, 55.0) is None     # 음수 가격
    assert m.lev_convert(100.0, 50.0, float("nan")) is None  # NaN


# ── mock supabase client (test_targets 패턴 확장) ───────────
class _Resp:
    def __init__(self, data):
        self.data = data


class _Table:
    def __init__(self, calls, name, data):
        self._calls, self._name, self._data = calls, name, data

    def select(self, *a, **k):
        self._calls.append(("select", self._name, a)); return self

    def insert(self, payload):
        self._calls.append(("insert", self._name, payload)); return self

    def update(self, payload):
        self._calls.append(("update", self._name, payload)); return self

    def delete(self):
        self._calls.append(("delete", self._name)); return self

    def eq(self, col, val):
        self._calls.append(("eq", col, val)); return self

    def order(self, *a, **k):
        self._calls.append(("order", a)); return self

    def limit(self, n):
        self._calls.append(("limit", n)); return self

    def execute(self):
        return _Resp(self._data)


class _Client:
    def __init__(self, calls, data_by_table=None):
        self._calls, self._data = calls, (data_by_table or {})

    def table(self, name):
        return _Table(self._calls, name, self._data.get(name, []))


def _patch(monkeypatch, data_by_table=None):
    calls = []
    monkeypatch.setattr(db, "client", lambda: _Client(calls, data_by_table))
    return calls


# ── CRUD ────────────────────────────────────────────────────
def test_list_filters_by_group_and_status(monkeypatch):
    calls = _patch(monkeypatch, {"trade_records": [{"id": "1", "symbol": "NVDA"}]})
    out = db.list_trade_records("US", "waiting")
    assert out == [{"id": "1", "symbol": "NVDA"}]
    assert ("eq", "market_group", "US") in calls
    assert ("eq", "status", "waiting") in calls


def test_list_returns_none_on_error(monkeypatch):
    def boom():
        raise RuntimeError("table missing")
    monkeypatch.setattr(db, "client", boom)
    assert db.list_trade_records("KR", "waiting") is None   # 테이블 미존재 → 안내용 None


def test_upsert_insert_when_no_id(monkeypatch):
    calls = _patch(monkeypatch, {"trade_records": [{"id": "new-uuid"}]})
    rid = db.upsert_trade_record({"market_group": "KR", "status": "waiting",
                                  "record_date": "2026-07-08", "symbol": "005490"})
    inserts = [c for c in calls if c[0] == "insert"]
    assert len(inserts) == 1 and inserts[0][1] == "trade_records"
    assert inserts[0][2]["symbol"] == "005490"
    assert "updated_at" in inserts[0][2]
    assert rid == "new-uuid"
    assert not any(c[0] == "update" for c in calls)


def test_upsert_update_when_id(monkeypatch):
    calls = _patch(monkeypatch)
    rid = db.upsert_trade_record({"id": "abc", "status": "entered"})
    ups = [c for c in calls if c[0] == "update"]
    assert len(ups) == 1 and ups[0][2]["status"] == "entered"
    assert "id" not in ups[0][2]                 # payload에 id 미포함(eq 조건으로만)
    assert ("eq", "id", "abc") in calls
    assert rid == "abc"


def test_edit_payload_updates_all_fields(monkeypatch):
    """수정 폼 payload(id 포함, 가격/리스크/메모/완료손익) → update 경로로 전체 전달."""
    calls = _patch(monkeypatch)
    payload = {
        "id": "rec-1", "record_date": "2026-07-10", "symbol": "NVDA",
        "leverage_symbol": "NVDL",
        "entry1": 195.0, "entry2": 185.0, "entry3": None, "entry4": None,
        "tp1": 220.0, "tp2": 240.0, "stop": 155.0,
        "risk1": 80.0, "risk2": 80.0, "risk3": None, "risk4": None,
        "realized_tp1_profit": 120.5, "realized_tp2_profit": None,
        "realized_stop_loss": -30.0, "realized_total_pnl": 90.5,
        "memo": "수정 테스트",
    }
    rid = db.upsert_trade_record(payload)
    ups = [c for c in calls if c[0] == "update"]
    assert len(ups) == 1 and rid == "rec-1"
    body = ups[0][2]
    assert body["symbol"] == "NVDA" and body["entry1"] == 195.0
    assert body["stop"] == 155.0 and body["risk2"] == 80.0
    assert body["realized_tp1_profit"] == 120.5
    assert body["realized_stop_loss"] == -30.0          # 음수 손익도 그대로 전달
    assert body["memo"] == "수정 테스트"
    assert "id" not in body and ("eq", "id", "rec-1") in calls
    assert not any(c[0] == "insert" for c in calls)      # 수정은 insert 안 탐


def test_delete_trade_record(monkeypatch):
    calls = _patch(monkeypatch)
    db.delete_trade_record("abc")
    assert ("delete", "trade_records") in calls
    assert ("eq", "id", "abc") in calls


# ── 가격 조회 폴백 ──────────────────────────────────────────
def test_get_latest_price_stocks_first(monkeypatch):
    _patch(monkeypatch, {"stocks": [{"close": 310.66}], "prices": [{"close": 999.0}]})
    assert db.get_latest_price("AAPL") == 310.66


def test_get_latest_price_prices_fallback(monkeypatch):
    _patch(monkeypatch, {"stocks": [], "prices": [{"close": 123.45}]})
    assert db.get_latest_price("TQQQ") == 123.45


def test_get_latest_price_none(monkeypatch):
    _patch(monkeypatch, {"stocks": [], "prices": []})
    assert db.get_latest_price("ZZZZ") is None


def test_get_latest_quote_stocks_first(monkeypatch):
    _patch(monkeypatch, {"stocks": [{"close": 310.66, "data_date": "2026-07-10"}],
                         "prices": [{"close": 999.0, "date": "2026-07-11"}]})
    assert db.get_latest_quote("AAPL") == {"price": 310.66, "asof": "2026-07-10"}


def test_get_latest_quote_prices_fallback(monkeypatch):
    _patch(monkeypatch, {"stocks": [], "prices": [{"close": 123.45, "date": "2026-07-11"}]})
    assert db.get_latest_quote("TQQQ") == {"price": 123.45, "asof": "2026-07-11"}


def test_get_latest_quote_none(monkeypatch):
    _patch(monkeypatch, {"stocks": [], "prices": []})
    assert db.get_latest_quote("ZZZZ") is None


def test_get_latest_quote_skips_zero_or_nan_close(monkeypatch):
    # stocks.close가 0/NaN이면 무효 → prices 최신으로 폴백
    _patch(monkeypatch, {"stocks": [{"close": 0, "data_date": "2026-07-10"}],
                         "prices": [{"close": 123.45, "date": "2026-07-11"}]})
    assert db.get_latest_quote("TQQQ") == {"price": 123.45, "asof": "2026-07-11"}
    _patch(monkeypatch, {"stocks": [{"close": float("nan"), "data_date": "2026-07-10"}],
                         "prices": []})
    assert db.get_latest_quote("TQQQ") is None


# ── 회귀: stale 모듈 AttributeError 재발 방지 ────────────────
def test_database_module_has_quote_functions():
    """app.database에 새 QuoteProvider가 쓰는 함수가 실제 존재해야 한다."""
    assert hasattr(db, "get_latest_quote")
    assert hasattr(db, "get_common_close_pair")
    assert hasattr(db, "latest_common_close")


def test_dashboard_db_calls_all_exist():
    """dashboard/app.py가 호출하는 모든 db.<fn>이 app.database에 실제 존재해야 한다.
    (실행 중 서버의 stale 모듈에서만 드러나던 AttributeError를 테스트 시점에 차단)"""
    import re
    with open(os.path.join(ROOT, "dashboard", "app.py"), encoding="utf-8") as f:
        src = f.read()
    called = sorted(set(re.findall(r"\bdb\.([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", src)))
    missing = [fn for fn in called if not hasattr(db, fn)]
    assert not missing, f"app.database에 없는 함수 호출: {missing}"
    assert "get_latest_quote" in called          # 새 경로가 실제로 쓰이는지도 확인


def test_db_provider_get_single_real_module_path(monkeypatch):
    """DatabaseQuoteProvider.get_single이 실제 db.get_latest_quote 경로로 동작
    (db 함수 monkeypatch 없이 Supabase client 계층만 mock)."""
    m = _dash()
    _patch(monkeypatch, {"stocks": [{"close": 61.5, "data_date": "2026-07-10"}]})
    s = m.DatabaseQuoteProvider().get_single("TEM")
    assert s == {"symbol": "TEM", "price": 61.5,
                 "source": "Supabase", "asof": "2026-07-10"}


def test_db_provider_get_single_none_when_no_data(monkeypatch):
    m = _dash()
    _patch(monkeypatch, {"stocks": [], "prices": []})
    assert m.DatabaseQuoteProvider().get_single("ZZZZ") is None


def test_trade_calc_single_stock_via_real_db_path(monkeypatch):
    """본주 단독 _trade_calc가 client mock만으로(AttributeError 없이) 끝까지 동작."""
    m = _dash()
    _patch(monkeypatch, {"stocks": [{"close": 190.0, "data_date": "2026-07-10"}]})
    r = {"market_group": "US", "symbol": "TEM", "leverage_symbol": None,
         "entry1": 190.0, "stop": 180.0, "risk1": 70.0}
    c = m._trade_calc(r)
    assert c["base_now"] == 190.0 and c["trade_now"] == 190.0 and c["qty1"] == 7
    assert "Supabase" in c["basis"] and "2026-07-10" in c["basis"]
