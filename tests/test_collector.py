"""
tests/test_collector.py — 수집기 폴백/hold 경로 (외부 소스 mock)
"""
import datetime as dt
import pandas as pd
from app import collector
from app import config


def test_fetch_fallback_to_hold(monkeypatch):
    # pykrx/FDR 모두 실패 시 예외 없이 hold 반환
    monkeypatch.setattr(config, "DATA_GO_KR_KEY", "")  # 공공API 비활성 → pykrx/fdr 경로만
    monkeypatch.setattr(collector, "_fetch_pykrx", lambda *a, **k: None)
    monkeypatch.setattr(collector, "_fetch_fdr", lambda *a, **k: None)
    monkeypatch.setattr(collector.time, "sleep", lambda *_: None)
    r = collector.fetch_stock("000000", "테스트", "KOSPI", dt.date(2026, 6, 19))
    assert r["status"] == "hold"
    assert r["ohlcv"] is None


def test_fetch_primary_success(monkeypatch):
    df = pd.DataFrame({"close": [1], "volume": [1], "value": [1]},
                      index=[dt.date(2026, 6, 19)])
    monkeypatch.setattr(config, "DATA_GO_KR_KEY", "")  # 공공API 비활성 → pykrx가 주 소스
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
    # 공공 API가 실제 거래대금(trPrc)·고가(hipr)를 주는 정상 경로. 파싱·정확코드 필터 검증.
    payload = {"response": {"body": {"items": {"item": [
        {"basDt": "20260618", "srtnCd": "005490", "clpr": "367000", "hipr": "381000",
         "trqu": "429197", "trPrc": "159000000000"},
        {"basDt": "20260619", "srtnCd": "005490", "clpr": "356500", "hipr": "372000",
         "trqu": "535534", "trPrc": "190000000000"},
        # likeSrtnCd 부분일치로 섞일 수 있는 다른 종목 → 제외돼야 함
        {"basDt": "20260619", "srtnCd": "0054901", "clpr": "1", "trqu": "1", "trPrc": "1"},
    ]}}}}
    monkeypatch.setattr(config, "DATA_GO_KR_KEY", "TEST_KEY")
    monkeypatch.setattr(collector.requests, "get", lambda *a, **k: _FakeResp(payload))
    df = collector._fetch_datagokr("005490", dt.date(2025, 12, 19), dt.date(2026, 6, 19))
    assert list(df.columns) == ["close", "high", "volume", "value", "value_estimated"]
    assert len(df) == 2                       # 다른 종목(0054901) 제외
    assert df["value"].iloc[-1] == 190000000000
    assert df["high"].iloc[-1] == 372000      # 장중 고가 파싱
    assert df["value_estimated"].any() == False   # 실제 거래대금 — 추정 아님


def test_fetch_datagokr_missing_hipr_safe(monkeypatch):
    # hipr가 없는 응답이어도 close 수집은 유지, high는 None(안전)
    payload = {"response": {"body": {"items": {"item": [
        {"basDt": "20260619", "srtnCd": "005490", "clpr": "356500",
         "trqu": "535534", "trPrc": "190000000000"},
    ]}}}}
    monkeypatch.setattr(config, "DATA_GO_KR_KEY", "TEST_KEY")
    monkeypatch.setattr(collector.requests, "get", lambda *a, **k: _FakeResp(payload))
    df = collector._fetch_datagokr("005490", dt.date(2025, 12, 19), dt.date(2026, 6, 19))
    assert df["close"].iloc[0] == 356500
    assert pd.isna(df["high"].iloc[0])        # 고가 없음 → NaN, 예외 없음


def test_fetch_pykrx_keeps_high(monkeypatch):
    # pykrx 원본(한국어 컬럼)에서 고가→high 유지
    class _FakeStock:
        @staticmethod
        def get_market_ohlcv(s, e, code):
            return pd.DataFrame({
                "시가": [100], "고가": [120], "저가": [90], "종가": [110],
                "거래량": [1000], "등락률": [1.0],
            }, index=[dt.date(2026, 6, 19)])
    monkeypatch.setattr(collector, "_import_pykrx", lambda: _FakeStock)
    df = collector._fetch_pykrx("005490", dt.date(2025, 6, 19), dt.date(2026, 6, 19))
    assert "high" in df.columns and df["high"].iloc[0] == 120
    assert df["close"].iloc[0] == 110


def test_fetch_fdr_keeps_high(monkeypatch):
    # FDR 원본(High)→high 유지. fetch_foreign이 _fetch_fdr 재사용이라 해외도 자동 반영.
    class _FakeFdr:
        @staticmethod
        def DataReader(code, s, e):
            return pd.DataFrame({
                "Open": [100.0], "High": [125.0], "Low": [95.0],
                "Close": [110.0], "Volume": [500],
            }, index=[dt.date(2026, 6, 19)])
    monkeypatch.setattr(collector, "_import_fdr", lambda: _FakeFdr)
    df = collector._fetch_fdr("AAPL", dt.date(2025, 6, 19), dt.date(2026, 6, 19))
    assert "high" in df.columns and df["high"].iloc[0] == 125.0
    assert df["close"].iloc[0] == 110.0
    assert df["value_estimated"].iloc[0] == True   # Amount 없음 → 근사


def test_fetch_fdr_missing_high_safe(monkeypatch):
    # High 컬럼이 없어도 close 수집은 깨지지 않음
    class _FakeFdr:
        @staticmethod
        def DataReader(code, s, e):
            return pd.DataFrame({"Close": [110.0], "Volume": [500]},
                                index=[dt.date(2026, 6, 19)])
    monkeypatch.setattr(collector, "_import_fdr", lambda: _FakeFdr)
    df = collector._fetch_fdr("AAPL", dt.date(2025, 6, 19), dt.date(2026, 6, 19))
    assert "high" not in df.columns           # 없으면 생략(안전)
    assert df["close"].iloc[0] == 110.0


def test_fetch_period_is_12_months(monkeypatch):
    # 수집 시작일이 end-12개월인지(FETCH_MONTHS). 분류용 6개월 상수는 별도 유지.
    captured = {}
    def fake_pykrx(code, start, end):
        captured["start"], captured["end"] = start, end
        return pd.DataFrame({"close": [1], "volume": [1], "value": [1]},
                            index=[dt.date(2026, 6, 19)])
    monkeypatch.setattr(config, "DATA_GO_KR_KEY", "")
    monkeypatch.setattr(collector, "_fetch_pykrx", fake_pykrx)
    monkeypatch.setattr(collector.time, "sleep", lambda *_: None)
    collector.fetch_stock("005490", "POSCO홀딩스", "KOSPI", dt.date(2026, 6, 19))
    days = (captured["end"] - captured["start"]).days
    assert 360 <= days <= 370                  # 12개월
    assert collector.FETCH_MONTHS == 12
    assert config.LOOKBACK_MONTHS == 6         # 분류 기준 유지


def test_classification_unchanged_with_12m_data():
    # 12개월 df를 넣어도 분류는 최근 6개월만 사용(과거 6개월 폭등값 무시 → swing 유지)
    from app import classifier as C
    end = dt.date(2026, 6, 19)
    idx = pd.bdate_range(end - pd.Timedelta(days=365), end)
    old = idx[idx < pd.Timestamp(end) - pd.Timedelta(days=185)]
    recent = idx[idx >= pd.Timestamp(end) - pd.Timedelta(days=185)]
    # 합성 데이터(로직 검증 전용): 과거엔 5,000억/일, 최근 6개월은 800억/일
    vals = [5000 * 10**8] * len(old) + [800 * 10**8] * len(recent)
    df = pd.DataFrame({"close": [10000] * len(idx), "high": [10500] * len(idx),
                       "volume": [1000] * len(idx), "value": vals}, index=idx)
    r = C.classify_one({"code": "T", "name": "T", "market": "KOSPI", "ohlcv": df,
                        "status": "ok", "reason": ""}, end)
    assert r["classification"] == "swing"      # 과거 폭등값이 섞였다면 sector가 됐을 것


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


def _fdr_df():
    """FDR 형태 합성 일봉(로직 검증 전용 — 실제 시세 아님)."""
    idx = [dt.date(2026, 6, 17), dt.date(2026, 6, 18), dt.date(2026, 6, 19)]
    return pd.DataFrame({
        "close": [100.0, 105.0, 110.0],
        "volume": [10, 20, 30],
        "value": [1000.0, 2100.0, 3300.0],
        "value_estimated": [True, True, True],
    }, index=idx)


def test_fetch_foreign_ok(monkeypatch):
    # FDR 정상 df → 최신/이전 종가·등락률 계산, status ok
    monkeypatch.setattr(collector, "_fetch_fdr", lambda *a, **k: _fdr_df())
    r = collector.fetch_foreign("AAPL", "Apple", "NASDAQ", dt.date(2026, 6, 19))
    assert r["status"] == "ok"
    assert r["code"] == "AAPL" and r["source"] == "fdr"
    assert r["close"] == 110.0
    assert r["prev_close"] == 105.0
    assert r["change_pct"] == round((110.0 - 105.0) / 105.0 * 100, 2)  # +4.76
    assert r["ohlcv"] is not None and len(r["ohlcv"]) == 3


def test_fetch_foreign_empty_is_hold(monkeypatch):
    # 빈 데이터 → 예외 없이 hold, ohlcv None
    monkeypatch.setattr(collector, "_fetch_fdr", lambda *a, **k: None)
    r = collector.fetch_foreign("ZZZZ", "없는종목", "NASDAQ", dt.date(2026, 6, 19))
    assert r["status"] == "hold"
    assert r["ohlcv"] is None
    assert r["close"] is None


def test_fetch_foreign_exception_safe(monkeypatch):
    # FDR 호출 중 예외 → 전체로 안 터지고 hold 반환
    def boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(collector, "_fetch_fdr", boom)
    r = collector.fetch_foreign("AAPL", "Apple", "NASDAQ", dt.date(2026, 6, 19))
    assert r["status"] == "hold"
    assert r["ohlcv"] is None
    assert "fdr" in r["reason"]


def test_collect_foreign_iterates(monkeypatch):
    monkeypatch.setattr(collector, "_fetch_fdr", lambda *a, **k: _fdr_df())
    monkeypatch.setattr(collector.time, "sleep", lambda *_: None)
    stocks = [
        {"ticker": "AAPL", "name": "Apple", "market": "NASDAQ", "cc": "US", "origin_sector": "M7"},
        {"ticker": "NVDA", "name": "NVIDIA", "market": "NASDAQ", "cc": "US", "origin_sector": "M7"},
    ]
    out = collector.collect_foreign(stocks, dt.date(2026, 6, 19))
    assert len(out) == 2
    assert all(x["status"] == "ok" for x in out)
    assert out[0]["country"] == "US" and out[0]["origin_sector"] == "M7"


def test_fetch_fallback_to_secondary(monkeypatch):
    df = pd.DataFrame({"close": [1], "volume": [1], "value": [1], "value_estimated": [True]},
                      index=[dt.date(2026, 6, 19)])
    monkeypatch.setattr(config, "DATA_GO_KR_KEY", "")  # 공공API 비활성 → pykrx→fdr 폴백
    monkeypatch.setattr(collector, "_fetch_pykrx", lambda *a, **k: None)  # 주 실패
    monkeypatch.setattr(collector, "_fetch_fdr", lambda *a, **k: df)       # 예비 성공
    monkeypatch.setattr(collector.time, "sleep", lambda *_: None)
    r = collector.fetch_stock("042700", "한미반도체", "KOSPI", dt.date(2026, 6, 19))
    assert r["status"] == "ok"
    assert r["source"] == "fdr"
