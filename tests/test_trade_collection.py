"""매매기록 심볼(본주·레버리지 ETF) 가격 수집 단계 검증.
실제 Supabase/네트워크 없이 collector·db·watchlist를 mock으로 대체한다.
수집 대상 union·정규화(순수 로직) + 파이프라인 저장(장애 격리·prices 전용·idempotent)."""
import datetime as dt
import importlib

from app import collector
from app import database as db

END = dt.date(2026, 7, 10)


def _up():
    return importlib.import_module("scripts.run_daily_update")


# ── 순수 로직: 정규화 ───────────────────────────────────────
def test_normalize_pipeline_symbol():
    assert collector.normalize_pipeline_symbol("5930", "KR") == "005930"   # 숫자 zfill
    assert collector.normalize_pipeline_symbol("005930", "KR") == "005930"
    assert collector.normalize_pipeline_symbol("0193W0", "KR") == "0193W0"  # KR 비숫자 코드 유지
    assert collector.normalize_pipeline_symbol("nvda", "US") == "NVDA"      # 미국 대문자
    assert collector.normalize_pipeline_symbol("  tsll ", "US") == "TSLL"   # 공백 제거
    assert collector.normalize_pipeline_symbol("", "US") == ""
    assert collector.normalize_pipeline_symbol(None, "KR") == ""


# ── 순수 로직: 수집 대상 union ──────────────────────────────
def test_build_trade_targets_union_dedup_and_empty():
    rows = [
        {"market_group": "US", "symbol": "NVDA", "leverage_symbol": "NVDL"},
        {"market_group": "US", "symbol": "nvda", "leverage_symbol": ""},      # 중복 본주 + 빈 ETF
        {"market_group": "KR", "symbol": "5930", "leverage_symbol": "0193W0"},
        {"market_group": "US", "symbol": "TSLA", "leverage_symbol": None},    # None ETF 제외
    ]
    targets = collector.build_trade_targets(rows)
    assert ("US", "NVDA") in targets
    assert ("US", "NVDL") in targets
    assert ("KR", "005930") in targets                # zfill 정규화
    assert ("KR", "0193W0") in targets                # KR ETF 코드 유지
    assert ("US", "TSLA") in targets
    # 빈/None leverage_symbol은 대상에 없음
    assert all(code for _mg, code in targets)
    # 중복 제거 — NVDA 한 번만
    assert sum(1 for mg, c in targets if c == "NVDA") == 1


def test_build_trade_targets_plain_base_only():
    rows = [{"market_group": "KR", "symbol": "042700", "leverage_symbol": ""}]
    assert collector.build_trade_targets(rows) == [("KR", "042700")]   # 본주만


def test_build_trade_targets_empty_input():
    assert collector.build_trade_targets([]) == []
    assert collector.build_trade_targets(None) == []


# ── fixture: 34개 ETF가 수집 대상에 포함되는지 ───────────────
_ETF_PAIRS = [
    ("AAPL", "AAPU"), ("AMZN", "AMZU"), ("ANET", "ANEL"), ("AVGO", "AVGX"),
    ("BA", "BOEU"), ("COIN", "CONX"), ("EOSE", "EOSU"), ("GOOGL", "GGLL"),
    ("IREN", "IRE"), ("LUNR", "LUNL"), ("META", "METU"), ("MSFT", "MSFU"),
    ("MSTR", "MSTX"), ("MRVL", "MVLL"), ("NFLX", "NFXL"), ("NOW", "NOWL"),
    ("NVDA", "NVDL"), ("NVO", "NVOX"), ("OKLO", "OKLL"), ("ORCL", "ORCX"),
    ("PLTR", "PLTU"), ("PLUG", "PLUL"), ("RGTI", "RGTX"), ("RKLB", "RKLX"),
    ("HOOD", "ROBN"), ("SMCI", "SMCX"), ("SNOW", "SNOU"), ("SNDK", "SNXX"),
    ("TEM", "TEMT"), ("TER", "TERG"), ("TSLA", "TSLL"), ("UMAC", "UMAL"),
    ("UNH", "UNHG"), ("NVDA2", "MSFU2"),
]


def test_build_trade_targets_covers_all_etfs():
    rows = [{"market_group": "US", "symbol": b, "leverage_symbol": e} for b, e in _ETF_PAIRS]
    targets = collector.build_trade_targets(rows)
    etf_codes = {code for _mg, code in targets}
    for _base, etf in _ETF_PAIRS:
        assert etf.upper() in etf_codes, f"{etf} 수집 대상 누락"
    assert len(_ETF_PAIRS) == 34


# ── get_active_trade_symbols: 완료·비활성 제외 ───────────────
class _Resp:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, calls):
        self._calls = calls

    def select(self, *a, **k):
        self._calls.append(("select", a)); return self

    def in_(self, col, vals):
        self._calls.append(("in_", col, tuple(vals))); return self

    def execute(self):
        return _Resp([{"market_group": "US", "symbol": "NVDA", "leverage_symbol": "NVDL"}])


class _Cli:
    def __init__(self, calls):
        self._calls = calls

    def table(self, name):
        self._calls.append(("table", name)); return _Q(self._calls)


def test_get_active_trade_symbols_filters_active_only(monkeypatch):
    calls = []
    monkeypatch.setattr(db, "client", lambda: _Cli(calls))
    out = db.get_active_trade_symbols()
    assert out == [{"market_group": "US", "symbol": "NVDA", "leverage_symbol": "NVDL"}]
    # 활성 상태만 조회(완료 제외) — in_ 필터에 completed 없음
    in_call = [c for c in calls if c[0] == "in_"][0]
    assert in_call[1] == "status"
    assert set(in_call[2]) == {"waiting", "entered", "tp_in"}
    assert "completed" not in in_call[2]


def test_get_active_trade_symbols_safe_on_error(monkeypatch):
    def boom():
        raise RuntimeError("no table")
    monkeypatch.setattr(db, "client", boom)
    assert db.get_active_trade_symbols() == []


# ── 파이프라인 저장: 장애 격리 · prices 전용 · 스킵 · idempotent ──
class _DBTracker:
    """호출된 db 함수명을 기록 — prices 외 write 미호출 검증용."""
    def __init__(self, fail_codes=None):
        self.calls = []
        self.saved = []
        self.fail_codes = set(fail_codes or [])


def _setup_pipeline(monkeypatch, up, trade_rows, wl_kr=None, wl_us=None,
                    fail_codes=None, ohlcv_none=None, name_to_code=None):
    tracker = _DBTracker(fail_codes)

    monkeypatch.setattr(up.db, "get_active_trade_symbols",
                        lambda: (tracker.calls.append("get_active_trade_symbols") or trade_rows))
    monkeypatch.setattr(up.db, "code_by_name",
                        lambda n: (name_to_code or {}).get(str(n).strip()))
    monkeypatch.setattr(up.watchlist, "all_korean_stocks",
                        lambda: [{"code": c} for c in (wl_kr or [])])
    monkeypatch.setattr(up.watchlist, "all_global_stocks",
                        lambda: [{"ticker": t} for t in (wl_us or [])])

    def _fetch(code, name, market, end):
        if code in tracker.fail_codes:
            raise RuntimeError(f"{code} source down")
        if code in (ohlcv_none or set()):
            return {"code": code, "status": "hold", "ohlcv": None, "reason": "데이터 없음"}
        return {"code": code, "status": "ok", "ohlcv": object(), "market": market}

    monkeypatch.setattr(up.collector, "fetch_stock", _fetch)
    monkeypatch.setattr(up.collector, "fetch_foreign", _fetch)

    def _save_ohlcv(code, market, df):
        tracker.calls.append("save_ohlcv")
        tracker.saved.append(code)
        return 250
    monkeypatch.setattr(up.db, "save_ohlcv", _save_ohlcv)
    monkeypatch.setattr(up.db, "log_error",
                        lambda *a, **k: tracker.calls.append("log_error"))
    # prices 외 write 함수는 호출되면 즉시 실패하도록 감시
    for fn in ("save_classification", "upsert_trade_record", "delete_trade_record",
               "record_history", "set_meta"):
        monkeypatch.setattr(up.db, fn,
                            (lambda name: (lambda *a, **k: tracker.calls.append("FORBIDDEN:" + name)))(fn))
    return tracker


def test_save_trade_symbol_prices_collects_new_and_skips_watchlist(monkeypatch):
    up = _up()
    rows = [
        {"market_group": "US", "symbol": "NVDA", "leverage_symbol": "NVDL"},
        {"market_group": "US", "symbol": "AAPL", "leverage_symbol": "AAPU"},
    ]
    # NVDA·AAPL은 워치리스트에 이미 있음 → 스킵, ETF만 신규 수집
    tracker = _setup_pipeline(monkeypatch, up, rows, wl_us=["NVDA", "AAPL"])
    summary = up.save_trade_symbol_prices(END, "u", "")
    assert summary["collected"] == 2                 # NVDL, AAPU
    assert summary["skipped"] == 2                    # NVDA, AAPL (워치리스트)
    assert summary["failed"] == 0
    assert set(tracker.saved) == {"NVDL", "AAPU"}
    assert summary["saved_rows"] == 500               # 250 × 2


def test_save_trade_symbol_prices_isolates_failure(monkeypatch):
    up = _up()
    rows = [
        {"market_group": "US", "symbol": "NVDA", "leverage_symbol": "NVDL"},
        {"market_group": "US", "symbol": "TSLA", "leverage_symbol": "TSLL"},
    ]
    # NVDL 조회 실패(예외) → TSLL·나머지는 계속 진행
    tracker = _setup_pipeline(monkeypatch, up, rows, fail_codes={"NVDL"})
    summary = up.save_trade_symbol_prices(END, "u", "")
    assert "NVDL" in summary["fail_codes"] and summary["failed"] == 1
    assert "NVDL" not in tracker.saved
    assert {"NVDA", "TSLA", "TSLL"} <= set(tracker.saved)   # 실패 다음 심볼 계속 수집
    assert "log_error" in tracker.calls                     # 실패는 로그로 남김


def test_save_trade_symbol_prices_hold_counts_as_failure(monkeypatch):
    up = _up()
    rows = [{"market_group": "US", "symbol": "ZZZZ", "leverage_symbol": "ZZZU"}]
    tracker = _setup_pipeline(monkeypatch, up, rows, ohlcv_none={"ZZZU"})
    summary = up.save_trade_symbol_prices(END, "u", "")
    assert "ZZZU" in summary["fail_codes"]                  # ohlcv 없음 → 실패 집계
    assert "ZZZZ" in tracker.saved                          # 본주는 정상 저장


def test_save_trade_symbol_prices_only_touches_prices(monkeypatch):
    up = _up()
    rows = [{"market_group": "US", "symbol": "NVDA", "leverage_symbol": "NVDL"}]
    tracker = _setup_pipeline(monkeypatch, up, rows)
    up.save_trade_symbol_prices(END, "u", "")
    # prices(save_ohlcv) 외 write 함수 미호출
    assert not any(str(c).startswith("FORBIDDEN") for c in tracker.calls)
    assert "save_ohlcv" in tracker.calls


def test_looks_like_name():
    up = _up()
    assert up._looks_like_name("005930") is False        # KRX 숫자 코드
    assert up._looks_like_name("0193W0") is False         # KRX 영숫자 ETF 코드
    assert up._looks_like_name("파두") is True             # 한글 종목명
    assert up._looks_like_name("삼성전자") is True
    assert up._looks_like_name("HPSP") is True            # 6자 아님(길이 4)


def test_save_trade_symbol_prices_resolves_kr_name_to_watchlist(monkeypatch):
    up = _up()
    rows = [{"market_group": "KR", "symbol": "삼성전자", "leverage_symbol": "0193W0"}]
    # 삼성전자→005930(워치리스트) → 스킵, 0193W0(코드·워치리스트 밖) → 수집
    tracker = _setup_pipeline(monkeypatch, up, rows, wl_kr=["005930"],
                              name_to_code={"삼성전자": "005930"})
    summary = up.save_trade_symbol_prices(END, "u", "")
    assert summary["skipped"] == 1                        # 삼성전자→005930(워치리스트)
    assert "0193W0" in tracker.saved                      # KR ETF 코드는 수집
    assert summary["unresolved"] == 0


def test_save_trade_symbol_prices_unresolved_name_skipped(monkeypatch):
    up = _up()
    rows = [{"market_group": "KR", "symbol": "코데즈컴바인", "leverage_symbol": ""}]
    # 워치리스트/stocks에 없는 순수 종목명 → FDR 조회 불가 → 미해소 집계, fetch 안 함
    tracker = _setup_pipeline(monkeypatch, up, rows, name_to_code={})
    summary = up.save_trade_symbol_prices(END, "u", "")
    assert summary["unresolved"] == 1
    assert summary["failed"] == 0                          # 실패 아님(조회 시도조차 안 함)
    assert tracker.saved == []


def test_save_trade_symbol_prices_idempotent(monkeypatch):
    up = _up()
    rows = [{"market_group": "US", "symbol": "NVDA", "leverage_symbol": "NVDL"}]
    tracker = _setup_pipeline(monkeypatch, up, rows)
    s1 = up.save_trade_symbol_prices(END, "u", "")
    saved_first = list(tracker.saved)
    tracker.saved.clear()
    s2 = up.save_trade_symbol_prices(END, "u", "")
    # 재실행해도 같은 심볼을 upsert(save_ohlcv)만 — insert/delete 경로 없음
    assert s1 == s2
    assert set(saved_first) == set(tracker.saved) == {"NVDA", "NVDL"}
    assert not any(str(c).startswith("FORBIDDEN") for c in tracker.calls)
