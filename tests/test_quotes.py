"""가격 쌍 일관성(app/quotes.py + db 조회 + 대시보드 _trade_calc) 검증.
실제 Supabase/네트워크 없이 mock으로 검증한다."""
import os
import importlib.util

from app import database as db
from app import quotes as qt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _dash():
    """dashboard/app.py 모듈 로드 (가격 쌍 계산 검증용)."""
    p = os.path.join(ROOT, "dashboard", "app.py")
    spec = importlib.util.spec_from_file_location("dash_for_quote_test", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _snap(symbol="005490", price=100.0, provider="Supabase", as_of="2026-07-10"):
    return qt.QuoteSnapshot(symbol=symbol, price=price, provider=provider, as_of=as_of)


# ── QuotePair 일관성 판정 ───────────────────────────────────
def test_make_pair_consistent():
    pair = qt.make_pair(_snap("005490", 300000.0), _snap("46X910", 12000.0))
    assert pair.is_consistent is True
    assert pair.provider == "Supabase" and pair.as_of == "2026-07-10"
    assert pair.base.price == 300000.0 and pair.leverage.price == 12000.0


def test_make_pair_rejects_different_asof():
    pair = qt.make_pair(_snap(as_of="2026-07-10"), _snap(symbol="46X910", as_of="2026-07-09"))
    assert pair.is_consistent is False
    assert "기준일" in pair.reason


def test_make_pair_rejects_different_provider():
    pair = qt.make_pair(_snap(provider="Supabase"), _snap(symbol="46X910", provider="FDR"))
    assert pair.is_consistent is False
    assert "출처" in pair.reason


def test_make_pair_rejects_missing_or_invalid_price():
    assert qt.make_pair(None, _snap()).is_consistent is False
    assert qt.make_pair(_snap(), None).is_consistent is False
    assert qt.make_pair(_snap(price=0), _snap()).is_consistent is False
    assert qt.make_pair(_snap(), _snap(price=None)).is_consistent is False
    assert qt.make_pair(_snap(as_of=None), _snap(as_of=None)).is_consistent is False


# ── 최신 공통 거래일 선택 ───────────────────────────────────
def test_latest_common_close_picks_latest_common_day():
    rows_a = [{"date": "2026-07-11", "close": 101.0}, {"date": "2026-07-10", "close": 100.0},
              {"date": "2026-07-09", "close": 99.0}]
    rows_b = [{"date": "2026-07-10", "close": 51.0}, {"date": "2026-07-09", "close": 50.0}]
    # a의 최신(7-11)은 b에 없음 → 공통 최신 7-10 선택
    assert qt.latest_common_close(rows_a, rows_b) == ("2026-07-10", 100.0, 51.0)


def test_latest_common_close_no_common_day():
    rows_a = [{"date": "2026-07-11", "close": 101.0}]
    rows_b = [{"date": "2026-07-10", "close": 51.0}]
    assert qt.latest_common_close(rows_a, rows_b) is None
    assert qt.latest_common_close([], rows_b) is None
    assert qt.latest_common_close(None, None) is None


def test_latest_common_close_skips_invalid_close():
    rows_a = [{"date": "2026-07-11", "close": 0}, {"date": "2026-07-10", "close": 100.0}]
    rows_b = [{"date": "2026-07-11", "close": 51.0}, {"date": "2026-07-10", "close": 50.0}]
    # 7-11의 a close가 0(무효) → 7-10으로 내려감
    assert qt.latest_common_close(rows_a, rows_b) == ("2026-07-10", 100.0, 50.0)


# ── 외부(FDR) 한 쌍 조회 ────────────────────────────────────
def test_fetch_fdr_pair_success(monkeypatch):
    snaps = {"005490": _snap("005490", 300000.0, "FDR", "2026-07-13"),
             "46X910": _snap("46X910", 12000.0, "FDR", "2026-07-13")}
    monkeypatch.setattr(qt, "fetch_fdr_snapshot", lambda s: snaps.get(str(s)))
    pair = qt.fetch_fdr_pair("005490", "46X910")
    assert pair.is_consistent is True and pair.provider == "FDR"


def test_fetch_fdr_pair_one_side_failure(monkeypatch):
    snaps = {"005490": _snap("005490", 300000.0, "FDR", "2026-07-13")}
    monkeypatch.setattr(qt, "fetch_fdr_snapshot", lambda s: snaps.get(str(s)))
    pair = qt.fetch_fdr_pair("005490", "46X910")
    assert pair is not None and pair.is_consistent is False   # 한 종목 실패 → 사용 금지
    monkeypatch.setattr(qt, "fetch_fdr_snapshot", lambda s: None)
    assert qt.fetch_fdr_pair("005490", "46X910") is None      # 양쪽 실패 → None


def test_fetch_fdr_pair_asof_mismatch(monkeypatch):
    snaps = {"005490": _snap("005490", 300000.0, "FDR", "2026-07-13"),
             "46X910": _snap("46X910", 12000.0, "FDR", "2026-07-12")}
    monkeypatch.setattr(qt, "fetch_fdr_snapshot", lambda s: snaps.get(str(s)))
    assert qt.fetch_fdr_pair("005490", "46X910").is_consistent is False


# ── mock supabase client (code별 데이터 분리) ────────────────
class _Resp:
    def __init__(self, data):
        self.data = data


class _Table:
    def __init__(self, name, data_by_key):
        self._name, self._data, self._code = name, data_by_key, None

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        if col == "code":
            self._code = str(val)
        return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def execute(self):
        return _Resp(self._data.get((self._name, self._code), []))


class _Client:
    def __init__(self, data_by_key):
        self._data = data_by_key

    def table(self, name):
        return _Table(name, self._data)


def _patch_db(monkeypatch, data_by_key):
    monkeypatch.setattr(db, "client", lambda: _Client(data_by_key))


# ── db.get_common_close_pair / get_latest_quote ─────────────
def test_db_common_close_pair(monkeypatch):
    _patch_db(monkeypatch, {
        ("prices", "005490"): [{"date": "2026-07-11", "close": 310000.0},
                               {"date": "2026-07-10", "close": 300000.0}],
        ("prices", "46X910"): [{"date": "2026-07-10", "close": 12000.0},
                               {"date": "2026-07-09", "close": 11500.0}],
    })
    assert db.get_common_close_pair("005490", "46X910") == ("2026-07-10", 300000.0, 12000.0)


def test_db_common_close_pair_none(monkeypatch):
    _patch_db(monkeypatch, {
        ("prices", "005490"): [{"date": "2026-07-11", "close": 310000.0}],
        ("prices", "46X910"): [],
    })
    assert db.get_common_close_pair("005490", "46X910") is None


def test_db_get_latest_quote_stocks_first(monkeypatch):
    _patch_db(monkeypatch, {
        ("stocks", "005490"): [{"close": 300000.0, "data_date": "2026-07-11"}],
        ("prices", "005490"): [{"close": 999.0, "date": "2026-07-01"}],
    })
    assert db.get_latest_quote("005490") == {"price": 300000.0, "as_of": "2026-07-11"}


def test_db_get_latest_quote_prices_fallback_and_none(monkeypatch):
    _patch_db(monkeypatch, {
        ("stocks", "46X910"): [],
        ("prices", "46X910"): [{"close": 12000.0, "date": "2026-07-10"}],
    })
    assert db.get_latest_quote("46X910") == {"price": 12000.0, "as_of": "2026-07-10"}
    _patch_db(monkeypatch, {})
    assert db.get_latest_quote("ZZZZ") is None


# ── database 함수 실제 존재·import 검증 (AttributeError 재발 방지) ──
def test_database_functions_exist():
    assert callable(getattr(db, "get_latest_quote"))
    assert callable(getattr(db, "get_common_close_pair"))
    assert callable(getattr(db, "get_latest_price"))


def test_dashboard_imports_quote_layer():
    m = _dash()
    for name in ("db_quote_pair", "db_single_quote", "fdr_quote_pair",
                 "fdr_single_quote", "clear_price_caches", "_trade_calc",
                 "_resolve_symbol", "_basis_caption"):
        assert hasattr(m, name), f"dashboard/app.py에 {name} 없음"
    assert m.qt is qt                     # dashboard가 실제 app.quotes를 import


# ── _trade_calc: ETF 환산 / 본주 단독 / 보류 ─────────────────
def _calc_with(monkeypatch, m, pair=None, single=None):
    monkeypatch.setattr(m, "db_quote_pair", lambda a, b: pair)
    monkeypatch.setattr(m, "db_single_quote", lambda s: single)
    monkeypatch.setattr(m, "_ext_quote", lambda rid: None)


def test_trade_calc_lev_consistent_pair(monkeypatch):
    m = _dash()
    pair = qt.make_pair(_snap("005490", 100.0), _snap("46X910", 200.0))
    _calc_with(monkeypatch, m, pair=pair)
    r = {"id": "r1", "market_group": "KR", "symbol": "005490",
         "leverage_symbol": "46X910", "entry1": 110.0, "stop": 95.0, "risk1": 700.0}
    c = m._trade_calc(r)
    assert c["consistent"] is True and c["provider"] == "Supabase"
    assert c["as_of"] == "2026-07-10"
    assert c["base_now"] == 100.0 and c["etf_now"] == 200.0 and c["trade_now"] == 200.0
    # 환산: 200 × (1 + 0.10×2) = 240 / 손절 200 × (1 − 0.05×2) = 180
    assert c["e1_lev"] == 240.0 and c["stop_lev"] == 180.0
    # 수량 = 700 ÷ (240−180) = 11.67 → 일반 반올림 12
    assert c["qty1"] == 12
    assert c["total_risk"] == 700.0                    # 기존 합계 규칙 보존


def test_trade_calc_lev_no_common_day(monkeypatch):
    m = _dash()
    _calc_with(monkeypatch, m, pair=None)
    r = {"id": "r2", "market_group": "KR", "symbol": "005490",
         "leverage_symbol": "46X910", "entry1": 110.0, "stop": 95.0, "risk1": 700.0}
    c = m._trade_calc(r)
    assert c["consistent"] is False and c["reason"] == m.NO_COMMON_DAY_MSG
    assert c["e1_lev"] is None and c["stop_lev"] is None and c["qty1"] is None
    assert c["trade_now"] is None                      # 환산·표시 보류


def test_trade_calc_lev_inconsistent_pair(monkeypatch):
    m = _dash()
    pair = qt.make_pair(_snap("005490", 100.0, as_of="2026-07-10"),
                        _snap("46X910", 200.0, as_of="2026-07-09"))
    _calc_with(monkeypatch, m, pair=pair)
    r = {"id": "r3", "market_group": "KR", "symbol": "005490",
         "leverage_symbol": "46X910", "entry1": 110.0, "stop": 95.0, "risk1": 700.0}
    c = m._trade_calc(r)
    assert c["consistent"] is False and "기준일" in c["reason"]
    assert c["e1_lev"] is None and c["qty1"] is None


def test_trade_calc_plain_stock(monkeypatch):
    m = _dash()
    _calc_with(monkeypatch, m, single=_snap("005490", 100.0))
    r = {"id": "r4", "market_group": "KR", "symbol": "005490",
         "leverage_symbol": "", "entry1": 110.0, "stop": 95.0, "risk1": 30.0}
    c = m._trade_calc(r)
    assert c["consistent"] is True and c["is_lev"] is False
    assert c["base_now"] == 100.0 and c["trade_now"] == 100.0
    assert c["e1_lev"] == 110.0 and c["stop_lev"] == 95.0   # 본주 단독: 환산=본주가
    assert c["qty1"] == 2                                   # 30 ÷ 15 = 2
    assert c["provider"] == "Supabase" and c["as_of"] == "2026-07-10"


def test_trade_calc_qty_normal_rounding(monkeypatch):
    m = _dash()
    _calc_with(monkeypatch, m, single=_snap("005490", 100.0))
    r = {"id": "r5", "market_group": "KR", "symbol": "005490",
         "leverage_symbol": "", "entry1": 30.0, "stop": 20.0, "risk1": 45.0}
    c = m._trade_calc(r)
    assert c["qty1"] == 5                                   # 4.50 → 5 (일반 반올림)


def test_basis_caption(monkeypatch):
    m = _dash()
    pair = qt.make_pair(_snap("005490", 100.0), _snap("46X910", 200.0))
    _calc_with(monkeypatch, m, pair=pair)
    r = {"id": "r6", "market_group": "KR", "symbol": "005490",
         "leverage_symbol": "46X910"}
    c = m._trade_calc(r)
    line = m._basis_caption(c, "KRW")
    assert "가격 출처 Supabase" in line and "기준일 2026-07-10" in line
    assert "본주" in line and "ETF" in line
    # 보류 상태면 출처가 없어 근거줄도 없음
    _calc_with(monkeypatch, m, pair=None)
    assert m._basis_caption(m._trade_calc(r), "KRW") is None


def test_calc_total_pnl_preserved():
    """기존 완료 손익 합산 규칙(1+2+3차 − |손절|)이 이번 변경으로 바뀌지 않았는지."""
    m = _dash()
    assert m.calc_total_pnl(50000, 30000, 20000, 10000) == 90000
    assert m.calc_total_pnl(50000, None, None, -10000) == 40000
