"""
tests/test_run_update.py — 일일 파이프라인의 해외 저장 단계 검증.
실제 Supabase/네트워크에 연결하지 않고 collector·db·watchlist를 mock으로 대체한다.
"""
import datetime as dt
import importlib


def _up():
    return importlib.import_module("scripts.run_daily_update")


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
