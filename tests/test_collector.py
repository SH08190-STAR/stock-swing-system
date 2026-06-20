"""
tests/test_collector.py — 수집기 폴백/hold 경로 (외부 소스 mock)
"""
import datetime as dt
import pandas as pd
from app import collector
from app import config


def test_fetch_fallback_to_hold(monkeypatch):
    # pykrx/FDR 모두 실패 시 예외 없이 hold 반환
    monkeypatch.setattr(collector, "_fetch_pykrx", lambda *a, **k: None)
    monkeypatch.setattr(collector, "_fetch_fdr", lambda *a, **k: None)
    monkeypatch.setattr(collector.time, "sleep", lambda *_: None)
    r = collector.fetch_stock("000000", "테스트", "KOSPI", dt.date(2026, 6, 19))
    assert r["status"] == "hold"
    assert r["ohlcv"] is None


def test_fetch_primary_success(monkeypatch):
    df = pd.DataFrame({"close": [1], "volume": [1], "value": [1]},
                      index=[dt.date(2026, 6, 19)])
    monkeypatch.setattr(collector, "_fetch_pykrx", lambda *a, **k: df)
    monkeypatch.setattr(collector.time, "sleep", lambda *_: None)
    r = collector.fetch_stock("042700", "한미반도체", "KOSPI", dt.date(2026, 6, 19))
    assert r["status"] == "ok"
    assert r["source"] == "pykrx"


class _FakeResp:
    """공공데이터포털 응답 mock (로직 검증 전용 합성 데이터 — 실제 시세 아님)."""
    def __init__(self, payload):
        self._payload = payload
    def raise_for_status(self):
        pass
    def json(self):
        return self._payload


def test_fetch_datagokr_parses_real_value(monkeypatch):
    # 공공 API가 실제 거래대금(trPrc)을 주는 정상 경로. 파싱·정확코드 필터 검증.
    payload = {"response": {"body": {"items": {"item": [
        {"basDt": "20260618", "srtnCd": "005490", "clpr": "367000",
         "trqu": "429197", "trPrc": "159000000000"},
        {"basDt": "20260619", "srtnCd": "005490", "clpr": "356500",
         "trqu": "535534", "trPrc": "190000000000"},
        # likeSrtnCd 부분일치로 섞일 수 있는 다른 종목 → 제외돼야 함
        {"basDt": "20260619", "srtnCd": "0054901", "clpr": "1", "trqu": "1", "trPrc": "1"},
    ]}}}}
    monkeypatch.setattr(config, "DATA_GO_KR_KEY", "TEST_KEY")
    monkeypatch.setattr(collector.requests, "get", lambda *a, **k: _FakeResp(payload))
    df = collector._fetch_datagokr("005490", dt.date(2025, 12, 19), dt.date(2026, 6, 19))
    assert list(df.columns) == ["close", "volume", "value", "value_estimated"]
    assert len(df) == 2                       # 다른 종목(0054901) 제외
    assert df["value"].iloc[-1] == 190000000000
    assert df["value_estimated"].any() == False   # 실제 거래대금 — 추정 아님


def test_datagokr_is_primary_when_key_set(monkeypatch):
    # 키가 있으면 datagokr가 pykrx보다 먼저 시도된다.
    df = pd.DataFrame({"close": [1], "volume": [1], "value": [9]},
                      index=[dt.date(2026, 6, 19)])
    monkeypatch.setattr(config, "DATA_GO_KR_KEY", "TEST_KEY")
    monkeypatch.setattr(collector, "_fetch_datagokr", lambda *a, **k: df)
    monkeypatch.setattr(collector, "_fetch_pykrx", lambda *a, **k: (_ for _ in ()).throw(AssertionError("pykrx가 먼저 호출되면 안 됨")))
    monkeypatch.setattr(collector.time, "sleep", lambda *_: None)
    r = collector.fetch_stock("005490", "POSCO홀딩스", "KOSPI", dt.date(2026, 6, 19))
    assert r["status"] == "ok"
    assert r["source"] == "datagokr"


def test_fetch_fallback_to_secondary(monkeypatch):
    df = pd.DataFrame({"close": [1], "volume": [1], "value": [1], "value_estimated": [True]},
                      index=[dt.date(2026, 6, 19)])
    monkeypatch.setattr(collector, "_fetch_pykrx", lambda *a, **k: None)  # 주 실패
    monkeypatch.setattr(collector, "_fetch_fdr", lambda *a, **k: df)       # 예비 성공
    monkeypatch.setattr(collector.time, "sleep", lambda *_: None)
    r = collector.fetch_stock("042700", "한미반도체", "KOSPI", dt.date(2026, 6, 19))
    assert r["status"] == "ok"
    assert r["source"] == "fdr"
