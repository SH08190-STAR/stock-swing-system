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


# ── basis caption: USD $...$ Markdown 수식 렌더링 방지 ───────
def test_basis_caption_usd_lev_escapes_dollar():
    """미장 레버리지: $가 2개라 escape 없으면 $...$ 구간이 수식으로 렌더됨."""
    m = _dash()
    c = {"provider": "Supabase", "as_of": "2026-07-10",
         "base_now": 1915.92, "etf_now": 28.06, "is_lev": True}
    s = m._basis_caption(c, "USD")
    assert "\\$1,915.92" in s and "\\$28.06" in s
    assert s.count("$") == s.count("\\$")          # unescaped $ 없음
    assert "가격 출처 Supabase" in s and "기준일 2026-07-10" in s


def test_basis_caption_usd_single_escapes_dollar():
    """미장 본주 단독도 동일하게 escape(카드 간 일관 표시)."""
    m = _dash()
    c = {"provider": "Supabase", "as_of": "2026-07-10",
         "base_now": 123.45, "is_lev": False}
    s = m._basis_caption(c, "USD")
    assert "\\$123.45" in s and s.count("$") == s.count("\\$")


def test_basis_caption_krw_unchanged():
    """국장 원화 표시는 기존 문자열 그대로($ 없음 → escape 무영향)."""
    m = _dash()
    c = {"provider": "Supabase", "as_of": "2026-07-10",
         "base_now": 78000.0, "etf_now": 12340.0, "is_lev": True}
    s = m._basis_caption(c, "KRW")
    assert s == "가격 출처 Supabase · 기준일 2026-07-10 · 본주 78,000원 · ETF 12,340원"
    assert "\\" not in s and "$" not in s


def test_basis_caption_none_without_provider():
    m = _dash()
    assert m._basis_caption({"provider": None}, "USD") is None
