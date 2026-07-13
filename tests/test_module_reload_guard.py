"""Streamlit Cloud 부분 hot-reload 대비 모듈 정합성 가드 검증.
정상 시 reload 안 함, 계약 불일치(속성 누락/API 버전) 시 1회 reload 복구,
복구 실패 시 안전 중단, reload 시에만 cache clear, 가격 함수 예외 격리, ETF 계산 회귀 없음."""
import os
import types
import importlib
import importlib.util

import pytest

from app import quotes as qt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _dash():
    p = os.path.join(ROOT, "dashboard", "app.py")
    spec = importlib.util.spec_from_file_location("dash_guard_test", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ── fake 모듈/loader (순수 함수 check_and_recover_modules 검증용) ──
def _fake_db(with_all=True, api=2):
    m = types.SimpleNamespace(_role="db", MODULE_API_VERSION=api)
    if with_all:
        m.get_latest_quote = lambda s: None
        m.get_common_close_pair = lambda a, b: None
        m.get_active_trade_symbols = lambda: []
        m.code_by_name = lambda n: None
    return m


def _fake_qt(with_all=True, api=1):
    m = types.SimpleNamespace(_role="qt", MODULE_API_VERSION=api)
    if with_all:
        m.QuoteSnapshot = object
        m.QuotePair = object
        m.make_pair = lambda *a: None
    return m


class _FakeIl:
    """reload가 지정된 '복구본'을 돌려주는 fake importlib."""
    def __init__(self, db_after, qt_after):
        self.after = {"db": db_after, "qt": qt_after}
        self.invalidated = False
        self.reloaded = []

    def invalidate_caches(self):
        self.invalidated = True

    def reload(self, mod):
        self.reloaded.append(mod._role)
        return self.after[mod._role]


def test_normal_modules_no_reload():
    m = _dash()
    il = _FakeIl(_fake_db(), _fake_qt())
    d, q, status = m.check_and_recover_modules(_fake_db(), _fake_qt(), importlib_mod=il)
    assert status["reloaded"] is False and status["recovered"] is True
    assert il.reloaded == [] and status["cache_cleared"] is False


def test_missing_get_latest_quote_reloads_and_recovers():
    m = _dash()
    stale = _fake_db(with_all=True); del stale.get_latest_quote      # 누락 주입
    il = _FakeIl(_fake_db(), _fake_qt())                            # reload → 복구본
    cleared = []
    d, q, status = m.check_and_recover_modules(stale, _fake_qt(), importlib_mod=il,
                                               cache_clear=lambda: cleared.append(1))
    assert "database.get_latest_quote" in status["gaps_before"]
    assert status["reloaded"] is True and status["recovered"] is True
    assert il.invalidated is True and hasattr(d, "get_latest_quote")
    assert status["cache_cleared"] is True and cleared == [1]


def test_missing_get_common_close_pair_reloads_and_recovers():
    m = _dash()
    stale = _fake_db(with_all=True); del stale.get_common_close_pair
    il = _FakeIl(_fake_db(), _fake_qt())
    d, q, status = m.check_and_recover_modules(stale, _fake_qt(), importlib_mod=il)
    assert "database.get_common_close_pair" in status["gaps_before"]
    assert status["reloaded"] and status["recovered"]


def test_api_version_mismatch_reloads():
    m = _dash()
    stale = _fake_db(with_all=True, api=1)          # 함수는 있지만 버전 불일치
    il = _FakeIl(_fake_db(api=2), _fake_qt())
    d, q, status = m.check_and_recover_modules(stale, _fake_qt(), importlib_mod=il)
    assert any("MODULE_API_VERSION" in g for g in status["gaps_before"])
    assert status["reloaded"] and status["recovered"]


def test_reload_still_missing_safe_stop():
    m = _dash()
    stale = _fake_db(with_all=False)                # 함수 없음
    still_bad = _fake_db(with_all=False)            # reload 후에도 여전히 없음
    il = _FakeIl(still_bad, _fake_qt())
    cleared = []
    d, q, status = m.check_and_recover_modules(stale, _fake_qt(), importlib_mod=il,
                                               cache_clear=lambda: cleared.append(1))
    assert status["reloaded"] is True and status["recovered"] is False
    assert status["cache_cleared"] is False and cleared == []   # 복구 실패 시 clear 안 함


def test_cache_clear_only_when_reloaded():
    m = _dash()
    cleared = []
    # 정상 → reload 없음 → clear 없음
    m.check_and_recover_modules(_fake_db(), _fake_qt(), importlib_mod=_FakeIl(_fake_db(), _fake_qt()),
                                cache_clear=lambda: cleared.append(1))
    assert cleared == []


# ── 실제 stale 모듈 주입 재현 (실제 reload가 디스크에서 복구하는지) ──
def test_real_stale_database_reload_recovers():
    import app.database as realdb
    import app.quotes as realqt
    saved = (getattr(realdb, "get_latest_quote"), getattr(realdb, "get_common_close_pair"),
             realdb.MODULE_API_VERSION)
    try:
        del realdb.get_latest_quote            # 부분 hot-reload로 함수 사라진 상태 모사
        del realdb.get_common_close_pair
        realdb.MODULE_API_VERSION = 1
        _dash()                                # dashboard 로드 시 top-level 가드가 실제 reload 복구
        import app.database as after
        assert hasattr(after, "get_latest_quote") and hasattr(after, "get_common_close_pair")
        assert after.MODULE_API_VERSION == 2   # 디스크 최신본으로 복구
    finally:
        importlib.reload(realdb)               # 원상복구(다른 테스트 보호)
        importlib.reload(realqt)


# ── 가격 함수 예외 격리 (전체 탭으로 전파 금지) ──
def test_db_quote_pair_isolates_exception(monkeypatch):
    m = _dash()
    def boom(a, b):
        raise AttributeError("module 'app.database' has no attribute 'get_common_close_pair'")
    monkeypatch.setattr(m.db, "get_common_close_pair", boom)
    m.db_quote_pair.clear()
    assert m.db_quote_pair("NVDA", "NVDL") is None          # 예외 대신 None(보류)


def test_db_single_quote_isolates_exception(monkeypatch):
    m = _dash()
    def boom(s):
        raise AttributeError("no attribute 'get_latest_quote'")
    monkeypatch.setattr(m.db, "get_latest_quote", boom)
    m.db_single_quote.clear()
    assert m.db_single_quote("005490") is None


# ── ETF 계산 회귀 없음 (일관 쌍이면 기존대로 2배 환산) ──
def test_etf_calc_regression_ok(monkeypatch):
    m = _dash()
    pair = qt.make_pair(qt.QuoteSnapshot("005490", 100.0, "Supabase", "2026-07-10"),
                        qt.QuoteSnapshot("46X910", 200.0, "Supabase", "2026-07-10"))
    monkeypatch.setattr(m, "db_quote_pair", lambda a, b: pair)
    monkeypatch.setattr(m, "_ext_quote", lambda rid: None)
    r = {"id": "x", "market_group": "KR", "symbol": "005490",
         "leverage_symbol": "46X910", "entry1": 110.0, "stop": 95.0, "risk1": 700.0}
    c = m._trade_calc(r)
    assert c["consistent"] is True and c["e1_lev"] == 240.0 and c["stop_lev"] == 180.0
    assert c["qty1"] == 12
