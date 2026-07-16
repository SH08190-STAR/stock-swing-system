"""Toss live overlay(Relay 경유) 검증 — 순수 selection·conversion·fallback + 대시보드 배선.

실제 Relay/Toss 네트워크 호출은 0회다(FakeTossClient·monkeypatch만 사용).
DOM·픽셀·Streamlit 내부 클래스에 결합하지 않고, 계약(우선순위·일관성·fallback)만 본다.
아래 URL/token은 형식만 흉내 낸 가짜 값이다(실제 발급값 아님).
overlay 순수 로직은 TossPrice/RelayPrice 어느 쪽이든 동일 속성 계약으로 동작한다."""
import os
import importlib.util
import datetime as dt
from decimal import Decimal

import pytest

from app import toss_overlay as tov
from app.toss import TossPrice
from app.toss_relay_client import (TossRelayError, TossRelayAuthError,
                                   TossRelayRateLimitError, TossRelayTimeoutError,
                                   TossRelayUpstreamError, TossRelayResponseError)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FAKE_RELAY_URL = "https://fake-relay.example.dev"          # 가짜 값 — 비밀 아님
FAKE_RELAY_TOKEN = "relay_FAKE_OVERLAY_TOKEN_0123456789AB"  # 40자 가짜
LEAK_STRINGS = (FAKE_RELAY_TOKEN, "Authorization", "Bearer")


def _dash():
    """dashboard/app.py 모듈 로드(배선 검증용) — 매 테스트 fresh 캐시."""
    p = os.path.join(ROOT, "dashboard", "app.py")
    spec = importlib.util.spec_from_file_location("dash_for_overlay_test", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def tprice(sym, price, ts, currency="KRW"):
    return TossPrice(symbol=sym, last_price=Decimal(str(price)), currency=currency,
                     timestamp=dt.datetime.fromisoformat(ts))


class FakeTossClient:
    """TossClient 대역 — get_prices 계약만 흉내. 네트워크 없음."""

    def __init__(self, result=None, raises=None):
        self.result = result or {}
        self.raises = raises
        self.calls = []

    def get_prices(self, symbols):
        self.calls.append(list(symbols))
        if self.raises is not None:
            raise self.raises
        return dict(self.result)


# ══ 순수 로직: toss_overlay ═════════════════════════════════
# ── 1~2. credentials 게이트 ─────────────────────────────────
def test_is_configured_both_one_none():
    assert tov.is_configured(FAKE_RELAY_URL, FAKE_RELAY_TOKEN) is True
    assert tov.is_configured(FAKE_RELAY_URL, "") is False
    assert tov.is_configured("", FAKE_RELAY_TOKEN) is False
    assert tov.is_configured(None, None) is False
    assert tov.is_configured("  ", FAKE_RELAY_TOKEN) is False   # 공백만 → 미설정


# ── 5. visible 심볼 수집(중복 제거·순서·resolve) ────────────
def test_collect_visible_symbols_dedupe_and_order():
    resolve = lambda s, mg: str(s).strip().upper()
    records = [
        {"market_group": "US", "symbol": "nvda", "leverage_symbol": "NVDL"},
        {"market_group": "US", "symbol": "NVDA", "leverage_symbol": ""},      # 중복 본주·빈 ETF
        {"market_group": "KR", "symbol": "005490", "leverage_symbol": "46X910"},
        {"market_group": "US", "symbol": "TSLA", "leverage_symbol": None},    # None ETF 제외
    ]
    out = tov.collect_visible_symbols(records, resolve)
    assert out == ["NVDA", "NVDL", "005490", "46X910", "TSLA"]   # 순서 유지·중복 1회
    assert tov.collect_visible_symbols([], resolve) == []
    assert tov.collect_visible_symbols(None, resolve) == []


# ── 6~9. 레버리지 쌍 성립 / provider / timestamp 보존 ───────
def test_pick_pair_consistent_provider_and_individual_timestamps():
    overlay = {
        "005490": tprice("005490", "300000", "2026-07-15T15:30:00+09:00"),
        "46X910": tprice("46X910", "12000", "2026-07-15T15:29:30+09:00"),   # 30초 차이
    }
    pair = tov.pick_pair(overlay, "005490", "46X910")
    assert pair is not None and pair.is_consistent is True
    assert pair.provider == "Toss"
    assert pair.base.price == Decimal("300000") and pair.leverage.price == Decimal("12000")
    # 각 종목 timestamp 원본 보존 — batch라고 통일하지 않음
    assert pair.base.as_of == "2026-07-15T15:30:00+09:00"
    assert pair.leverage.as_of == "2026-07-15T15:29:30+09:00"
    assert pair.base.as_of != pair.leverage.as_of


def test_pick_pair_skew_within_5min_ok():
    overlay = {"A": tprice("A", "100", "2026-07-15T15:30:00+09:00"),
               "B": tprice("B", "200", "2026-07-15T15:25:01+09:00")}   # 4분59초
    assert tov.pick_pair(overlay, "A", "B") is not None


# ── 10~12. 쌍 fallback 조건 → None ──────────────────────────
def test_pick_pair_skew_over_5min_returns_none():
    overlay = {"A": tprice("A", "100", "2026-07-15T15:30:00+09:00"),
               "B": tprice("B", "200", "2026-07-15T15:24:59+09:00")}   # 5분1초
    assert tov.pick_pair(overlay, "A", "B") is None


def test_pick_pair_missing_side_returns_none():
    overlay = {"A": tprice("A", "100", "2026-07-15T15:30:00+09:00")}
    assert tov.pick_pair(overlay, "A", "B") is None      # ETF 누락
    assert tov.pick_pair({"B": overlay["A"]}, "A", "B") is None  # 본주 누락
    assert tov.pick_pair({}, "A", "B") is None


def test_pick_pair_invalid_price_returns_none():
    # 방어적: 가격이 0/음수면 무효 (TossPrice는 보통 양수 보장이나 계약 방어)
    bad = TossPrice("A", Decimal("0"), "KRW", dt.datetime.fromisoformat("2026-07-15T15:30:00+09:00"))
    overlay = {"A": bad, "B": tprice("B", "200", "2026-07-15T15:30:00+09:00")}
    assert tov.pick_pair(overlay, "A", "B") is None


# ── 14~15. 본주 단독 ────────────────────────────────────────
def test_pick_single_present_and_missing():
    overlay = {"NVDA": tprice("NVDA", "182.74", "2026-07-15T02:30:00+00:00", "USD")}
    snap = tov.pick_single(overlay, "nvda")              # 대소문자 무관 조회
    assert snap is not None and snap.provider == "Toss"
    assert snap.price == Decimal("182.74")
    assert tov.pick_single(overlay, "AAPL") is None      # 누락 → None
    assert tov.pick_single({}, "NVDA") is None


# ── 19. Decimal 정밀도 / currency 보존 ──────────────────────
def test_decimal_and_currency_preserved():
    tp = tprice("NVDA", "195.7400", "2026-07-15T02:30:00+00:00", "USD")
    assert isinstance(tp.last_price, Decimal) and str(tp.last_price) == "195.7400"
    assert tp.currency == "USD"                           # overlay dict에서 currency 유지
    snap = tov.pick_single({"NVDA": tp}, "NVDA")
    assert isinstance(snap.price, Decimal) and str(snap.price) == "195.7400"


# ══ 대시보드 배선: 활성/비활성 · fetch 격리 · 우선순위 ══════
# ── Fix 1: Relay 설정 비활성 = Toss 경로 완전 우회 (3997bb6 동일 경로) ──
def _set_creds(m, monkeypatch, url, token):
    monkeypatch.setattr(m.config, "TOSS_RELAY_URL", url)
    monkeypatch.setattr(m.config, "TOSS_RELAY_TOKEN", token)


def _pop_overlay_key(m):
    try:
        m.st.session_state.pop(m._TOSS_OVERLAY_KEY, None)
    except Exception:
        pass


def _spy(calls, name, ret=None):
    def f(*a, **k):
        calls.append(name)
        return ret
    return f


def test_dashboard_disabled_when_no_creds(monkeypatch):
    m = _dash()
    _set_creds(m, monkeypatch, "", "")
    assert m.toss_enabled() is False          # 순수 문자열 검사 — cache/client 미접근
    prices, err = m._fetch_toss_prices(None, ["005930"])   # client 없음 → 즉시 빈 결과
    assert prices == {} and err is None


def test_dashboard_disabled_with_one_cred(monkeypatch):
    m = _dash()
    _set_creds(m, monkeypatch, FAKE_RELAY_URL, "")          # URL만 → 비활성
    assert m.toss_enabled() is False
    _set_creds(m, monkeypatch, "", FAKE_RELAY_TOKEN)        # token만 → 비활성
    assert m.toss_enabled() is False


@pytest.mark.parametrize("url,token", [("", ""), (FAKE_RELAY_URL, ""),
                                       ("", FAKE_RELAY_TOKEN)])
def test_disabled_gate_runs_no_toss_paths(monkeypatch, url, token):
    """비활성(둘 다/한쪽 없음): 게이트가 client·raw·apply·심볼수집·info를 전부 우회하고
    session_state에 Toss key를 만들지 않으며 기존 key도 건드리지 않는다.
    필터 변경(서로 다른 records)을 반복해도 호출 0회."""
    m = _dash()
    _set_creds(m, monkeypatch, url, token)
    _pop_overlay_key(m)
    calls = []
    monkeypatch.setattr(m, "_toss_client", _spy(calls, "client"))
    monkeypatch.setattr(m, "_toss_overlay_raw", _spy(calls, "raw", {"prices": {}, "error": None}))
    monkeypatch.setattr(m, "_apply_toss_overlay", _spy(calls, "apply"))
    monkeypatch.setattr(m.tov, "collect_visible_symbols", _spy(calls, "collect", []))
    monkeypatch.setattr(m.st, "info", _spy(calls, "info"))
    m.st.session_state["_fix1_sentinel"] = "keep"
    filters = ([],
               [{"market_group": "US", "symbol": "NVDA", "leverage_symbol": "NVDL"}],
               [{"market_group": "KR", "symbol": "005490", "leverage_symbol": ""}])
    for recs in filters:                       # 필터 변경 3회 시뮬레이션
        assert m._maybe_apply_toss_overlay(recs) is False
    assert calls == []                          # Toss 함수·수집·안내 호출 0회
    assert m._TOSS_OVERLAY_KEY not in m.st.session_state   # Toss key 생성 0
    assert m.st.session_state.get("_fix1_sentinel") == "keep"  # 기존 값 무변경
    m.st.session_state.pop("_fix1_sentinel", None)


def test_disabled_trade_calc_uses_pure_db_path(monkeypatch):
    """비활성: _trade_calc가 tov helper를 한 번도 부르지 않고 기존 DB 경로 결과와 동일."""
    m = _dash()
    _set_creds(m, monkeypatch, "", "")
    _pop_overlay_key(m)                        # key 부재 → overlay {}
    monkeypatch.setattr(m, "_ext_quote", lambda rid: None)
    monkeypatch.setattr(m, "_resolve_symbol", lambda s, mg=None: str(s or "").upper())
    monkeypatch.setattr(m.tov, "pick_pair",
                        lambda *a, **k: pytest.fail("비활성 시 pick_pair 호출 금지"))
    monkeypatch.setattr(m.tov, "pick_single",
                        lambda *a, **k: pytest.fail("비활성 시 pick_single 호출 금지"))
    dbpair = m.qt.make_pair(m.qt.QuoteSnapshot("005490", 300000.0, "Supabase", "2026-07-10"),
                            m.qt.QuoteSnapshot("46X910", 12000.0, "Supabase", "2026-07-10"))
    monkeypatch.setattr(m, "db_quote_pair", lambda a, b: dbpair)
    c = m._trade_calc({"id": "r", "market_group": "KR", "symbol": "005490",
                       "leverage_symbol": "46X910", "entry1": 330000.0,
                       "stop": 285000.0, "risk1": 700.0})
    # 기존(3997bb6) DB 경로와 동일한 결과 계약
    assert c["provider"] == "Supabase" and c["consistent"] is True
    assert c["base_now"] == 300000.0 and c["etf_now"] == 12000.0
    assert c["as_of"] == "2026-07-10"
    # 본주 단독도 DB 경로만
    monkeypatch.setattr(m, "db_single_quote",
                        lambda s: m.qt.QuoteSnapshot("NVDA", 180.0, "Supabase", "2026-07-14"))
    c2 = m._trade_calc({"id": "s", "market_group": "US", "symbol": "NVDA",
                        "leverage_symbol": "", "stop": 150})
    assert c2["provider"] == "Supabase" and c2["base_now"] == 180.0


def test_dashboard_load_and_disabled_run_without_relay_import(monkeypatch):
    """dashboard 로드 + 비활성 경로 실행이 app.toss_relay_client(→requests)·app.toss
    import를 요구하지 않는다(비활성 프로세스에 로드 0)."""
    import sys
    saved_relay = sys.modules.pop("app.toss_relay_client", None)
    saved_toss = sys.modules.pop("app.toss", None)
    try:
        m = _dash()
        assert "app.toss_relay_client" not in sys.modules   # 모듈 로드만으로 import 없음
        assert "app.toss" not in sys.modules
        _set_creds(m, monkeypatch, "", "")
        _pop_overlay_key(m)
        assert m._maybe_apply_toss_overlay(
            [{"market_group": "US", "symbol": "NVDA", "leverage_symbol": "NVDL"}]) is False
        monkeypatch.setattr(m, "_ext_quote", lambda rid: None)
        monkeypatch.setattr(m, "_resolve_symbol", lambda s, mg=None: str(s or "").upper())
        monkeypatch.setattr(m, "db_single_quote", lambda s: None)
        m._trade_calc({"id": "x", "market_group": "US", "symbol": "NVDA",
                       "leverage_symbol": "", "stop": 1})
        assert "app.toss_relay_client" not in sys.modules   # 비활성 실행 후에도 import 없음
        assert "app.toss" not in sys.modules
    finally:
        if saved_relay is not None:
            sys.modules["app.toss_relay_client"] = saved_relay
        if saved_toss is not None:
            sys.modules["app.toss"] = saved_toss


def test_enabled_gate_calls_apply_once(monkeypatch):
    """활성: 게이트가 _apply_toss_overlay를 정확히 1회 호출."""
    m = _dash()
    _set_creds(m, monkeypatch, FAKE_RELAY_URL, FAKE_RELAY_TOKEN)
    called = []
    monkeypatch.setattr(m, "_apply_toss_overlay", lambda recs: called.append(list(recs)))
    assert m._maybe_apply_toss_overlay([{"symbol": "NVDA"}]) is True
    assert len(called) == 1


def test_toss_client_never_caches_none(monkeypatch):
    """_toss_client는 유효한 TossRelayClient만 반환 — None을 cache_resource에 저장 안 함.
    빈 설정으로 잘못 호출되면(게이트 밖) 예외로 방어(예외는 캐시되지 않음)."""
    m = _dash()
    m._toss_client.clear()
    _set_creds(m, monkeypatch, FAKE_RELAY_URL, FAKE_RELAY_TOKEN)
    c = m._toss_client()
    assert c is not None and type(c).__name__ == "TossRelayClient"
    m._toss_client.clear()
    _set_creds(m, monkeypatch, "", "")
    with pytest.raises(TossRelayError):
        m._toss_client()
    m._toss_client.clear()


def test_dashboard_enabled_builds_and_reuses_client(monkeypatch):
    m = _dash()
    m._toss_client.clear()
    monkeypatch.setattr(m.config, "TOSS_RELAY_URL", FAKE_RELAY_URL)
    monkeypatch.setattr(m.config, "TOSS_RELAY_TOKEN", FAKE_RELAY_TOKEN)
    c1 = m._toss_client()
    c2 = m._toss_client()
    assert c1 is not None and c1 is c2                    # cache_resource 재사용
    assert type(c1).__name__ == "TossRelayClient"
    for s in LEAK_STRINGS:                              # repr에 token 비노출
        assert s not in repr(c1)


# ── 4. 같은 cache 구간 batch 재사용 ─────────────────────────
def test_overlay_raw_caches_batch(monkeypatch):
    m = _dash()
    m._toss_overlay_raw.clear()          # cache_data도 _dash() 재로드 간 공유 → 초기화
    fake = FakeTossClient(result={"005930": tprice("005930", "79300", "2026-07-15T15:30:00+09:00")})
    monkeypatch.setattr(m, "_toss_client", lambda: fake)
    r1 = m._toss_overlay_raw(("005930",))
    r2 = m._toss_overlay_raw(("005930",))
    assert r1["prices"]["005930"].last_price == Decimal("79300")
    assert r2["error"] is None
    assert len(fake.calls) == 1                           # 20초 캐시 — 재조회 없음


# ── 16~20. Relay 오류 → 전부 격리(빈 dict + 타입명), 재시도 없음 ──
@pytest.mark.parametrize("exc,tag", [
    (TossRelayAuthError("Relay 인증 실패 (401)"), "TossRelayAuthError"),
    (TossRelayRateLimitError("Relay 호출 한도 초과 (429)", 7), "TossRelayRateLimitError"),
    (TossRelayTimeoutError("Relay 요청 timeout"), "TossRelayTimeoutError"),
    (TossRelayUpstreamError("Relay 상류 오류 (502)", "TOSS_IP_FORBIDDEN"),
     "TossRelayUpstreamError"),
    (TossRelayUpstreamError("Relay 상류 오류 (503)", "TOSS_AUTH_FAILED"),
     "TossRelayUpstreamError"),
    (TossRelayResponseError("Relay 응답 provider 오류"), "TossRelayResponseError"),
    (TossRelayError("Relay 네트워크 오류"), "TossRelayError"),
    (RuntimeError("unexpected boom"), "TossUnexpected"),
])
def test_fetch_isolates_all_errors(monkeypatch, exc, tag):
    m = _dash()
    fake = FakeTossClient(raises=exc)
    prices, err = m._fetch_toss_prices(fake, ["005930"])
    assert prices == {} and err == tag                   # 예외 전파 없이 빈 dict
    assert len(fake.calls) == 1                           # 자동 재시도 없음(429 포함)


def test_fetch_success_returns_prices(monkeypatch):
    m = _dash()
    fake = FakeTossClient(result={"005930": tprice("005930", "79300", "2026-07-15T15:30:00+09:00")})
    prices, err = m._fetch_toss_prices(fake, ["005930"])
    assert err is None and prices["005930"].last_price == Decimal("79300")


# ── 6~7,13. _trade_calc: Toss 쌍 사용 / 부분성공 유지 ───────
def _no_ext(m, monkeypatch):
    monkeypatch.setattr(m, "_ext_quote", lambda rid: None)
    monkeypatch.setattr(m, "_resolve_symbol", lambda s, mg=None: str(s or "").upper())


def test_trade_calc_uses_toss_pair(monkeypatch):
    m = _dash()
    overlay = {"005490": tprice("005490", "300000", "2026-07-15T15:30:00+09:00"),
               "46X910": tprice("46X910", "12000", "2026-07-15T15:29:30+09:00")}
    monkeypatch.setattr(m, "_toss_overlay_state", lambda: overlay)
    _no_ext(m, monkeypatch)
    monkeypatch.setattr(m, "db_quote_pair",
                        lambda a, b: pytest.fail("Toss 성립 시 DB 호출 금지"))
    r = {"id": "r1", "market_group": "KR", "symbol": "005490",
         "leverage_symbol": "46X910", "entry1": 330000.0, "stop": 285000.0, "risk1": 700.0}
    c = m._trade_calc(r)
    assert c["provider"] == "Toss" and c["consistent"] is True
    assert c["base_now"] == Decimal("300000") and c["etf_now"] == Decimal("12000")
    assert c["base_as_of"] != c["etf_as_of"]             # 개별 timestamp 보존
    # 환산·수량 공식은 기존 그대로(2배 환산) — 값이 계산됨
    assert c["e1_lev"] is not None and c["stop_lev"] is not None


def test_trade_calc_partial_overlay_keeps_toss_for_complete_pair(monkeypatch):
    m = _dash()
    overlay = {"AAA": tprice("AAA", "100", "2026-07-15T15:30:00+09:00"),
               "AAL": tprice("AAL", "200", "2026-07-15T15:30:10+09:00"),
               "BBB": tprice("BBB", "50", "2026-07-15T15:30:00+09:00")}   # BBL 없음
    monkeypatch.setattr(m, "_toss_overlay_state", lambda: overlay)
    _no_ext(m, monkeypatch)
    dbpair = m.qt.make_pair(m.qt.QuoteSnapshot("BBB", 55.0, "Supabase", "2026-07-14"),
                            m.qt.QuoteSnapshot("BBL", 60.0, "Supabase", "2026-07-14"))
    monkeypatch.setattr(m, "db_quote_pair", lambda a, b: dbpair)
    ra = {"id": "a", "market_group": "US", "symbol": "AAA", "leverage_symbol": "AAL", "stop": 90}
    rb = {"id": "b", "market_group": "US", "symbol": "BBB", "leverage_symbol": "BBL", "stop": 45}
    assert m._trade_calc(ra)["provider"] == "Toss"       # 완전한 쌍은 Toss 유지
    assert m._trade_calc(rb)["provider"] == "Supabase"   # 누락 쌍만 DB fallback


# ── 10~12. skew/누락 → 쌍 전체 DB fallback ──────────────────
def test_trade_calc_skew_over_5min_falls_back_to_db(monkeypatch):
    m = _dash()
    overlay = {"AAA": tprice("AAA", "100", "2026-07-15T15:30:00+09:00"),
               "AAL": tprice("AAL", "200", "2026-07-15T15:20:00+09:00")}   # 10분 차이
    monkeypatch.setattr(m, "_toss_overlay_state", lambda: overlay)
    _no_ext(m, monkeypatch)
    dbpair = m.qt.make_pair(m.qt.QuoteSnapshot("AAA", 111.0, "Supabase", "2026-07-14"),
                            m.qt.QuoteSnapshot("AAL", 222.0, "Supabase", "2026-07-14"))
    monkeypatch.setattr(m, "db_quote_pair", lambda a, b: dbpair)
    c = m._trade_calc({"id": "x", "market_group": "US", "symbol": "AAA",
                       "leverage_symbol": "AAL", "stop": 90})
    assert c["provider"] == "Supabase" and c["base_now"] == 111.0


# ── 21. Toss+DB 혼합 금지(한쪽만 Toss면 쌍 전체 DB) ─────────
def test_trade_calc_no_mixing_toss_base_with_db_etf(monkeypatch):
    m = _dash()
    overlay = {"AAA": tprice("AAA", "100", "2026-07-15T15:30:00+09:00")}   # ETF 없음
    monkeypatch.setattr(m, "_toss_overlay_state", lambda: overlay)
    _no_ext(m, monkeypatch)
    dbpair = m.qt.make_pair(m.qt.QuoteSnapshot("AAA", 111.0, "Supabase", "2026-07-14"),
                            m.qt.QuoteSnapshot("AAL", 222.0, "Supabase", "2026-07-14"))
    monkeypatch.setattr(m, "db_quote_pair", lambda a, b: dbpair)
    c = m._trade_calc({"id": "x", "market_group": "US", "symbol": "AAA",
                       "leverage_symbol": "AAL", "stop": 90})
    assert c["provider"] == "Supabase"
    assert c["base_now"] == 111.0 and c["etf_now"] == 222.0   # Toss 100이 아니라 DB 쌍


# ── 14~15. 본주 단독 Toss → 없으면 DB ───────────────────────
def test_trade_calc_single_toss_then_db(monkeypatch):
    m = _dash()
    overlay = {"NVDA": tprice("NVDA", "182.7", "2026-07-15T02:30:00+00:00", "USD")}
    monkeypatch.setattr(m, "_toss_overlay_state", lambda: overlay)
    _no_ext(m, monkeypatch)
    r = {"id": "s", "market_group": "US", "symbol": "NVDA", "leverage_symbol": "", "stop": 150}
    c = m._trade_calc(r)
    assert c["provider"] == "Toss" and c["base_now"] == Decimal("182.7")
    # 누락 → DB 단독 quote fallback
    monkeypatch.setattr(m, "_toss_overlay_state", lambda: {})
    monkeypatch.setattr(m, "db_single_quote",
                        lambda s: m.qt.QuoteSnapshot("NVDA", 180.0, "Supabase", "2026-07-14"))
    c2 = m._trade_calc(r)
    assert c2["provider"] == "Supabase" and c2["base_now"] == 180.0


# ── 6.1 수동 외부조회(_ext_quote) 우선 보존 → Toss가 덮지 않음 ──
def test_trade_calc_manual_ext_quote_wins_over_toss(monkeypatch):
    m = _dash()
    overlay = {"AAA": tprice("AAA", "100", "2026-07-15T15:30:00+09:00"),
               "AAL": tprice("AAL", "200", "2026-07-15T15:30:00+09:00")}
    monkeypatch.setattr(m, "_toss_overlay_state", lambda: overlay)
    monkeypatch.setattr(m, "_resolve_symbol", lambda s, mg=None: str(s or "").upper())
    extpair = m.qt.make_pair(m.qt.QuoteSnapshot("AAA", 111.0, "FDR", "2026-07-15"),
                             m.qt.QuoteSnapshot("AAL", 222.0, "FDR", "2026-07-15"))
    monkeypatch.setattr(m, "_ext_quote", lambda rid: extpair)
    c = m._trade_calc({"id": "a", "market_group": "US", "symbol": "AAA",
                       "leverage_symbol": "AAL", "stop": 90})
    assert c["provider"] == "FDR"                         # 수동 조회 보존
    assert c["base_now"] == 111.0


# ── Toss 비활성/overlay 없음이면 기존 DB 경로 그대로(회귀 안전) ──
def test_trade_calc_no_overlay_uses_db(monkeypatch):
    m = _dash()
    monkeypatch.setattr(m, "_toss_overlay_state", lambda: {})   # overlay 없음
    _no_ext(m, monkeypatch)
    dbpair = m.qt.make_pair(m.qt.QuoteSnapshot("005490", 300000.0, "Supabase", "2026-07-10"),
                            m.qt.QuoteSnapshot("46X910", 12000.0, "Supabase", "2026-07-10"))
    monkeypatch.setattr(m, "db_quote_pair", lambda a, b: dbpair)
    c = m._trade_calc({"id": "r", "market_group": "KR", "symbol": "005490",
                       "leverage_symbol": "46X910", "entry1": 330000.0, "stop": 285000.0, "risk1": 700.0})
    assert c["provider"] == "Supabase" and c["consistent"] is True


# ── 22. 새로고침: Relay price 캐시만 clear, client(+token)는 유지 ──
def test_refresh_clears_price_cache_keeps_token(monkeypatch):
    m = _dash()
    m._toss_client.clear()
    monkeypatch.setattr(m.config, "TOSS_RELAY_URL", FAKE_RELAY_URL)
    monkeypatch.setattr(m.config, "TOSS_RELAY_TOKEN", FAKE_RELAY_TOKEN)
    c1 = m._toss_client()
    m.clear_price_caches()                               # 예외 없이 동작
    c2 = m._toss_client()
    assert c1 is c2                       # client(+relay token) 재생성 안 함


# ── 23. 예외/오류표식에 secret·token 비노출 ─────────────────
def test_no_secret_leak_in_fetch_errors(monkeypatch):
    m = _dash()
    for exc in (TossRelayAuthError("Relay 인증 실패 (401)"),
                TossRelayRateLimitError("Relay 호출 한도 초과 (429)", 7),
                TossRelayResponseError("Relay 응답 provider 오류")):
        fake = FakeTossClient(raises=exc)
        _prices, err = m._fetch_toss_prices(fake, ["005930"])
        for s in LEAK_STRINGS:                          # 오류표식은 타입명만
            assert s not in str(err)
            assert s not in str(exc)                       # 예외 메시지 자체도 안전


# ── 25. 회귀: 기존 quote-pair 계약(make_pair)이 provider 혼합을 여전히 거부 ──
def test_existing_make_pair_still_rejects_mixed_provider():
    # Toss 도입이 기존 provider/as_of 일관성 규칙을 바꾸지 않았는지 재확인
    a = tov.QuoteSnapshot("A", 100.0, "Toss", "2026-07-15T15:30:00+09:00")
    b = tov.QuoteSnapshot("B", 200.0, "Supabase", "2026-07-15T15:30:00+09:00")
    from app.quotes import make_pair
    assert make_pair(a, b).is_consistent is False         # 출처 혼합 거부 유지
