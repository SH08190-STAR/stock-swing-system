"""
tests/test_run_update.py — 일일 파이프라인의 해외 저장·52주 고점 계산 검증.
실제 Supabase/네트워크에 연결하지 않고 collector·db·watchlist를 mock으로 대체한다.
"""
import datetime as dt
import importlib

import pandas as pd


def _up():
    return importlib.import_module("scripts.run_daily_update")


END = dt.date(2026, 7, 10)


def _df(dates_values: list[tuple], with_high: bool = True):
    """합성 일봉(로직 검증 전용): [(날짜, close, high), ...]"""
    idx = [d for d, *_ in dates_values]
    close = [v[1] for v in dates_values]
    data = {"close": close}
    if with_high:
        data["high"] = [v[2] for v in dates_values]
    return pd.DataFrame(data, index=idx)


# ── calc_52w_high ───────────────────────────────────────────
def test_calc_52w_high_uses_high_max():
    up = _up()
    df = _df([(END - dt.timedelta(days=200), 100.0, 150.0),
              (END - dt.timedelta(days=100), 120.0, 130.0),
              (END, 110.0, 115.0)])
    assert up.calc_52w_high(df, END) == 150.0     # 장중 고가 기준 max


def test_calc_52w_high_excludes_older_than_365d():
    up = _up()
    df = _df([(END - dt.timedelta(days=400), 100.0, 999.0),   # 365일 밖 고점 → 제외
              (END - dt.timedelta(days=100), 120.0, 130.0),
              (END, 110.0, 115.0)])
    assert up.calc_52w_high(df, END) == 130.0


def test_calc_52w_high_close_fallback_for_missing_high():
    up = _up()
    df = _df([(END - dt.timedelta(days=100), 140.0, float("nan")),  # high 결측 → close 대체
              (END, 110.0, 115.0)])
    assert up.calc_52w_high(df, END) == 140.0
    # high 컬럼 자체가 없어도 close 기준으로 동작
    df2 = _df([(END - dt.timedelta(days=50), 125.0, None), (END, 110.0, None)], with_high=False)
    assert up.calc_52w_high(df2, END) == 125.0


def test_calc_52w_high_short_history_and_bad_values():
    up = _up()
    # 신규상장(52주 미만) → 보유 기간 내 고점
    df = _df([(END - dt.timedelta(days=30), 90.0, 95.0), (END, 100.0, 105.0)])
    assert up.calc_52w_high(df, END) == 105.0
    # 0/음수 제외
    df2 = _df([(END - dt.timedelta(days=10), 0.0, -5.0), (END, 100.0, 0.0)])
    assert up.calc_52w_high(df2, END) == 100.0    # high 0 → close 100 (fillna 아님·0 제외)
    # 빈/None 입력
    assert up.calc_52w_high(None, END) is None
    assert up.calc_52w_high(pd.DataFrame(), END) is None
    assert up.calc_52w_high(object(), END) is None   # 이상 입력도 예외 없이 None


# ── database 저장 payload (inline client mock) ──────────────
class _Resp:
    def __init__(self, data):
        self.data = data


class _Tbl:
    def __init__(self, calls, name):
        self._calls, self._name = calls, name

    def upsert(self, payload, on_conflict=None):
        self._calls.append((self._name, payload, on_conflict)); return self

    def execute(self):
        return _Resp([])


class _Cli:
    def __init__(self, calls):
        self._calls = calls

    def table(self, name):
        return _Tbl(self._calls, name)


def test_save_ohlcv_includes_high(monkeypatch):
    from app import database as db
    calls = []
    monkeypatch.setattr(db, "client", lambda: _Cli(calls))
    df = _df([(END - dt.timedelta(days=1), 100.0, 120.0),
              (END, 110.0, float("nan"))])                     # NaN high → None
    n = db.save_ohlcv("TEST", "KOSPI", df)
    assert n == 2
    rows = calls[0][1]
    assert rows[0]["high"] == 120.0
    assert rows[1]["high"] is None                             # NaN 안전 처리
    assert rows[0]["close"] == 100.0                           # 기존 필드 유지


def test_save_classification_includes_high_52w(monkeypatch):
    from app import database as db
    calls = []
    monkeypatch.setattr(db, "client", lambda: _Cli(calls))
    db.save_classification([{
        "code": "005490", "name": "POSCO홀딩스", "market": "KOSPI",
        "classification": "sector", "close": 315500.0, "high_52w": 401000.0,
    }], "2026-07-10", "u")
    payload = calls[0][1]
    assert payload["high_52w"] == 401000.0
    assert payload["classification"] == "sector"               # 기존 구조 유지
    # None 이면 필드 제외(이전값 보존 규칙)
    calls.clear()
    db.save_classification([{
        "code": "X", "name": "x", "market": "KOSDAQ",
        "classification": "hold", "high_52w": None,
    }], "2026-07-10", "u")
    assert "high_52w" not in calls[0][1]


# 1·2·3) 해외 ok 결과는 save_ohlcv + save_classification(global)로 저장, hold는 제외
def test_save_foreign_saves_ok_skips_hold(monkeypatch):
    up = _up()
    monkeypatch.setattr(up.watchlist, "all_global_stocks", lambda: [{"ticker": "AAPL"}])
    foreign = [
        {"code": "AAPL", "name": "Apple", "market": "NASDAQ", "origin_sector": "M7",
         "status": "ok", "ohlcv": object(), "close": 110.0, "change_pct": 1.2},
        {"code": "HOLDX", "name": "x", "market": "NYSE", "origin_sector": "y",
         "status": "hold", "ohlcv": None, "close": None},
    ]
    monkeypatch.setattr(up.collector, "collect_foreign", lambda *a, **k: foreign)
    saved_ohlcv = []
    monkeypatch.setattr(up.db, "save_ohlcv", lambda code, market, df: (saved_ohlcv.append(code) or 5))
    captured = {}
    monkeypatch.setattr(up.db, "save_classification",
                        lambda rows, data_date, updated_at: captured.update(rows=rows))

    n, days = up.save_foreign(dt.date(2026, 6, 19), "2026-06-19 16:40", "")

    assert n == 1 and days == 5
    assert saved_ohlcv == ["AAPL"]                  # ok만 일봉 저장, hold 제외
    rows = captured["rows"]
    assert len(rows) == 1
    assert rows[0]["code"] == "AAPL"
    assert rows[0]["classification"] == "global"    # 해외 = 표시 전용 고정
    assert rows[0]["close"] == 110.0
    assert rows[0]["change_pct"] == 1.2


# 해외 저장 rows 에 high_52w 포함(52주 고점 계산 연결)
def test_save_foreign_includes_high_52w(monkeypatch):
    up = _up()
    ohlcv = _df([(END - dt.timedelta(days=120), 100.0, 210.0), (END, 195.0, 199.0)])
    monkeypatch.setattr(up.watchlist, "all_global_stocks", lambda: [{"ticker": "NVDA"}])
    monkeypatch.setattr(up.collector, "collect_foreign", lambda *a, **k: [
        {"code": "NVDA", "name": "NVIDIA", "market": "NASDAQ", "origin_sector": "M7",
         "status": "ok", "ohlcv": ohlcv, "close": 195.0, "change_pct": 0.5},
    ])
    monkeypatch.setattr(up.db, "save_ohlcv", lambda *a, **k: 2)
    captured = {}
    monkeypatch.setattr(up.db, "save_classification",
                        lambda rows, *a, **k: captured.update(rows=rows))
    up.save_foreign(END, "u", "")
    assert captured["rows"][0]["high_52w"] == 210.0            # 52주 고점 포함
    assert captured["rows"][0]["classification"] == "global"


# 4) 0/None/NaN close 는 저장하지 않음
def test_save_foreign_excludes_bad_close(monkeypatch):
    up = _up()
    monkeypatch.setattr(up.watchlist, "all_global_stocks", lambda: [])
    foreign = [
        {"code": "A", "status": "ok", "ohlcv": object(), "close": 0, "market": "", "origin_sector": ""},
        {"code": "B", "status": "ok", "ohlcv": object(), "close": None, "market": "", "origin_sector": ""},
        {"code": "C", "status": "ok", "ohlcv": object(), "close": float("nan"), "market": "", "origin_sector": ""},
    ]
    monkeypatch.setattr(up.collector, "collect_foreign", lambda *a, **k: foreign)
    saved = []
    monkeypatch.setattr(up.db, "save_ohlcv", lambda *a, **k: saved.append(1) or 1)
    cls_calls = []
    monkeypatch.setattr(up.db, "save_classification", lambda rows, *a, **k: cls_calls.append(rows))

    n, days = up.save_foreign(dt.date(2026, 6, 19), "u", "")

    assert n == 0 and days == 0
    assert saved == []          # 일봉 저장 0
    assert cls_calls == []      # f_rows 비어 save_classification 미호출


# 5) 해외 단계 예외가 나도 main 전체가 죽지 않고, 한국 일일 알림은 발송된다
def test_main_foreign_failure_isolated(monkeypatch):
    up = _up()
    monkeypatch.setenv("FORCE_RUN", "1")
    monkeypatch.setattr(up.config, "validate_for_collector", lambda: None)
    monkeypatch.setattr(up.db, "get_meta", lambda k: None)
    monkeypatch.setattr(up.collector, "latest_trading_day", lambda *a, **k: dt.date(2026, 6, 19))
    monkeypatch.setattr(up.watchlist, "all_korean_stocks", lambda: [])
    monkeypatch.setattr(up.collector, "collect_all", lambda *a, **k: [])
    monkeypatch.setattr(up.classifier, "classify_all", lambda *a, **k: [])
    monkeypatch.setattr(up.db, "get_prev_classifications", lambda: {})
    monkeypatch.setattr(up.db, "get_prev_avg", lambda: {})
    monkeypatch.setattr(up.classifier, "diff_classifications",
                        lambda *a, **k: {"new_swing": [], "back_to_sector": [], "new_hold": []})
    monkeypatch.setattr(up.db, "save_classification", lambda *a, **k: None)
    monkeypatch.setattr(up.db, "record_history", lambda *a, **k: 0)
    monkeypatch.setattr(up.db, "set_meta", lambda *a, **k: None)
    monkeypatch.setattr(up.db, "log_error", lambda *a, **k: None)
    sent = []
    monkeypatch.setattr(up.notifier, "send", lambda msg: sent.append(msg))
    monkeypatch.setattr(up.notifier, "build_daily", lambda *a, **k: "DAILY")
    monkeypatch.setattr(up.notifier, "build_error", lambda *a, **k: "ERR")
    monkeypatch.setattr(up.watchlist, "all_global_stocks", lambda: [{"ticker": "AAPL"}])

    def boom(*a, **k):
        raise RuntimeError("foreign source down")
    monkeypatch.setattr(up.collector, "collect_foreign", boom)

    up.main()  # 예외 전파 없이 정상 종료해야 함
    assert "DAILY" in sent  # 한국 일일 알림은 정상 발송(해외 실패와 무관)
