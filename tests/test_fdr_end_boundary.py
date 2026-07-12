"""FDR end-exclusive 보정(미국 수집 전용) 검증.
FDR/yfinance DataReader end는 exclusive → latest_trading_day를 그대로 넘기면 최신 완료
거래일이 빠진다. fetch_fdr_through가 end+1로 포함시키고 이후 행은 잘라낸다. KR 경로 무변경."""
import datetime as dt
import pandas as pd

from app import collector


class _FakeFDR:
    """yfinance 백엔드 모사. exclusive=True면 [start, end)(end 미포함), False면 [start, end]."""
    def __init__(self, inclusive=False):
        self.inclusive = inclusive
        self.calls = []

    def DataReader(self, code, start, end):
        self.calls.append((code, start, end))
        s = dt.date.fromisoformat(start); e = dt.date.fromisoformat(end)
        days, d = [], s
        while d <= e:
            if d.weekday() < 5:                     # 영업일만(주말 제외)
                if d < e or (self.inclusive and d <= e):
                    days.append(d)
            d += dt.timedelta(days=1)
        idx = pd.DatetimeIndex(days)
        return pd.DataFrame({"Close": [100.0]*len(days), "High": [101.0]*len(days),
                             "Volume": [1000]*len(days)}, index=idx)


def _last(df):
    ix = df.index[-1]
    return ix.date() if hasattr(ix, "date") else ix


# ── provider가 exclusive임을 확인 (raw _fetch_fdr = KR 경로도 사용) ──
def test_fetch_fdr_raw_is_exclusive(monkeypatch):
    monkeypatch.setattr(collector, "_import_fdr", lambda: _FakeFDR(inclusive=False))
    df = collector._fetch_fdr("AAPL", dt.date(2026, 7, 1), dt.date(2026, 7, 10))
    assert _last(df) == dt.date(2026, 7, 9)        # end=07-10 → 07-09까지만(07-10 빠짐)


# ── helper 적용 후 최신 완료일(07-10) 포함 ──
def test_fetch_fdr_through_includes_last(monkeypatch):
    monkeypatch.setattr(collector, "_import_fdr", lambda: _FakeFDR(inclusive=False))
    df = collector.fetch_fdr_through("AAPL", dt.date(2026, 7, 1), dt.date(2026, 7, 10))
    assert _last(df) == dt.date(2026, 7, 10)       # 07-10 포함됨


def test_fdr_end_exclusive_helper():
    # 금요일(07-10) + 1 = 토요일(07-11)이어도 금요일이 포함되도록 end를 넘긴다
    assert collector.fdr_end_exclusive(dt.date(2026, 7, 10)) == dt.date(2026, 7, 11)


# ── 목표일 이후 데이터가 와도 목표일까지만 남긴다 ──
def test_fetch_fdr_through_caps_beyond_target(monkeypatch):
    # inclusive provider가 end(07-10)까지 돌려줘도, 목표 07-09면 07-10을 잘라낸다
    monkeypatch.setattr(collector, "_import_fdr", lambda: _FakeFDR(inclusive=True))
    df = collector.fetch_fdr_through("AAPL", dt.date(2026, 7, 1), dt.date(2026, 7, 9))
    assert _last(df) == dt.date(2026, 7, 9)
    assert all((ix.date() if hasattr(ix, "date") else ix) <= dt.date(2026, 7, 9)
               for ix in df.index)


# ── 주말 실행: 최신 완료 거래일(금요일) 유지, 주말 미포함 ──
def test_weekend_run_keeps_last_completed(monkeypatch):
    monkeypatch.setattr(collector, "_import_fdr", lambda: _FakeFDR(inclusive=False))
    # 일요일에 실행하되 end=직전 금요일(07-10)을 넘기는 상황
    df = collector.fetch_fdr_through("NVDA", dt.date(2026, 7, 1), dt.date(2026, 7, 10))
    dates = [(ix.date() if hasattr(ix, "date") else ix) for ix in df.index]
    assert dt.date(2026, 7, 10) in dates                       # 금요일 포함
    assert all(d.weekday() < 5 for d in dates)                 # 주말 없음
    assert max(dates) == dt.date(2026, 7, 10)


# ── 날짜 중복 없음 ──
def test_fetch_fdr_through_no_duplicate_dates(monkeypatch):
    monkeypatch.setattr(collector, "_import_fdr", lambda: _FakeFDR(inclusive=False))
    df = collector.fetch_fdr_through("META", dt.date(2026, 7, 1), dt.date(2026, 7, 10))
    dates = [(ix.date() if hasattr(ix, "date") else ix) for ix in df.index]
    assert len(dates) == len(set(dates))


# ── fetch_foreign(US)이 end 포함하도록 보정됨 ──
def test_fetch_foreign_includes_end_day(monkeypatch):
    monkeypatch.setattr(collector, "_import_fdr", lambda: _FakeFDR(inclusive=False))
    r = collector.fetch_foreign("AAPL", "Apple", "NASDAQ", dt.date(2026, 7, 10))
    assert r["status"] == "ok"
    assert _last(r["ohlcv"]) == dt.date(2026, 7, 10)           # 최신 완료일 포함


# ── KR 경로(fetch_stock의 FDR fallback)는 exclusive 그대로(무변경) ──
def test_kr_fdr_path_unchanged(monkeypatch):
    fake = _FakeFDR(inclusive=False)
    monkeypatch.setattr(collector, "_import_fdr", lambda: fake)
    # datagokr/pykrx는 막고 FDR fallback만 타게 함
    monkeypatch.setattr(collector.config, "DATA_GO_KR_KEY", "", raising=False)
    monkeypatch.setattr(collector, "_fetch_datagokr", lambda *a, **k: None)
    monkeypatch.setattr(collector, "_fetch_pykrx", lambda *a, **k: None)
    monkeypatch.setattr(collector.config, "PRIMARY_SOURCE", "fdr", raising=False)
    monkeypatch.setattr(collector.config, "FALLBACK_SOURCE", "fdr", raising=False)
    monkeypatch.setattr(collector.config, "MAX_RETRY", 1, raising=False)
    monkeypatch.setattr(collector.config, "REQUEST_SLEEP_SEC", 0, raising=False)
    r = collector.fetch_stock("005930", "삼성전자", "KOSPI", dt.date(2026, 7, 10))
    # KR FDR fallback은 end를 그대로(exclusive) 사용 → end 문자열이 07-10 (보정 +1 아님)
    fdr_ends = [end for _code, _start, end in fake.calls]
    assert "2026-07-10" in fdr_ends
    assert "2026-07-11" not in fdr_ends              # US처럼 +1 하지 않음(무변경)
