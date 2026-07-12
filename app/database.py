"""
database.py — Supabase(PostgreSQL) 저장/조회

원칙
- 수집 실패 시 기존 데이터를 삭제하거나 0원으로 덮어쓰지 않는다.
  (실패 종목은 classification='hold'로만 기록, 이전 정상값은 stocks 테이블에 보존)
- 같은 (code, date) 일봉은 upsert로 중복 저장 방지.
- 분류가 바뀐 종목만 history에 추가 기록.

테이블 스키마는 schema.sql 참고. 아래는 그 테이블을 다루는 헬퍼.
"""
from __future__ import annotations
import datetime as dt
from app import config

# 대시보드가 런타임 모듈 정합성을 확인하는 API 버전. quote-pair 함수(get_latest_quote,
# get_common_close_pair 등)를 추가한 배포부터 2. 이 모듈 API가 바뀌면 값을 올린다.
MODULE_API_VERSION = 2

_client = None


def client():
    """Supabase 클라이언트 (지연 초기화)."""
    global _client
    if _client is None:
        from supabase import create_client
        if not config.SUPABASE_URL or not config.SUPABASE_KEY:
            raise RuntimeError("SUPABASE_URL/KEY 미설정")
        _client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
    return _client


# ── 일봉 저장 (중복 방지 upsert) ────────────────────────────
def save_ohlcv(code: str, market: str, df) -> int:
    """
    종목 일봉을 prices 테이블에 upsert. (code,date) 복합 유니크.
    df: index=date, columns 일부에 close/volume/value
    반환: 저장 행 수
    """
    if df is None or len(df) == 0:
        return 0
    rows = []
    for ix, r in df.iterrows():
        d = ix.date() if hasattr(ix, "date") else ix
        val = r.get("value")
        rows.append({
            "code": code,
            "market": market,
            "date": d.isoformat(),
            "close": _num(r.get("close")),
            "high": _num(r.get("high")),          # 장중 고가(없거나 NaN이면 None)
            "volume": _num(r.get("volume")),
            "value": _num(val),
            "value_estimated": bool(r.get("value_estimated", False)),
        })
    # upsert: 같은 (code,date)면 갱신, 없으면 삽입 → 중복 저장 방지
    client().table("prices").upsert(rows, on_conflict="code,date").execute()
    return len(rows)


# ── 분류 결과 저장 ──────────────────────────────────────────
def save_classification(rows: list[dict], data_date: str, updated_at: str):
    """
    stocks 테이블 upsert(code 기준). 최신 분류/평균/표시값을 종목별 1행으로 유지.
    hold(보류)인 종목도 'hold'로 기록하되, avg_6m 등 수치가 None이면
    기존 수치를 덮어쓰지 않도록 None 필드는 제외한다(이전값 보존).
    """
    for c in rows:
        payload = {
            "code": c["code"],
            "name": c["name"],
            "market": c["market"],
            "origin_sector": c.get("origin_sector", ""),
            "origin_sub": c.get("origin_sub", ""),
            "tier": c.get("tier", ""),
            "classification": c["classification"],
            "data_date": data_date,
            "updated_at": updated_at,
            "reason": c.get("reason", ""),
            "estimated": bool(c.get("estimated", False)),
        }
        # 수치는 값이 있을 때만 기록(보류 시 이전값 보존)
        for k in ("avg_6m", "today_value", "short_avg", "close",
                  "change_pct", "used_days", "high_52w"):
            if c.get(k) is not None:
                payload[k] = c[k]
        client().table("stocks").upsert(payload, on_conflict="code").execute()


# ── 분류 이력 ───────────────────────────────────────────────
def get_prev_classifications() -> dict[str, str]:
    """stocks 테이블의 현재 분류 스냅샷(code→classification). 비교 기준."""
    try:
        res = client().table("stocks").select("code,classification").execute()
        return {r["code"]: r["classification"] for r in (res.data or [])}
    except Exception:
        return {}


def get_prev_avg() -> dict[str, int]:
    try:
        res = client().table("stocks").select("code,avg_6m").execute()
        return {r["code"]: r.get("avg_6m") for r in (res.data or [])}
    except Exception:
        return {}


def record_history(changes: dict, prev_avg: dict, data_date: str):
    """
    변경된 종목만 history 테이블에 추가.
    changes: classifier.diff_classifications 결과
    """
    label = {"swing": "단기스윙", "sector": "기존섹터", "hold": "확인보류", None: "신규"}
    rows = []
    def add(c, before, after, reason):
        rows.append({
            "change_date": data_date,
            "code": c["code"],
            "name": c.get("name", ""),
            "from_class": label.get(before, str(before)),
            "to_class": label.get(after, str(after)),
            "prev_avg_6m": prev_avg.get(c["code"]),
            "new_avg_6m": c.get("avg_6m"),
            "reason": reason,
        })
    for c in changes["new_swing"]:
        add(c, "sector", "swing", "6개월 평균 거래대금 1,000억 이하 → 단기스윙 편입")
    for c in changes["back_to_sector"]:
        add(c, "swing", "sector", "6개월 평균 거래대금 1,000억 초과 → 기존 섹터 복귀")
    for c in changes["new_hold"]:
        add(c, None, "hold", c.get("reason", "데이터 확인 보류"))
    if rows:
        client().table("history").insert(rows).execute()
    return len(rows)


# ── 오류 로그 ───────────────────────────────────────────────
def log_error(target: str, cause: str, retried: str, last_ok: str | None):
    try:
        client().table("errors").insert({
            "occurred_at": dt.datetime.utcnow().isoformat(),
            "target": target, "cause": cause,
            "retried": retried, "last_ok_update": last_ok,
        }).execute()
    except Exception:
        pass  # 오류 로깅 자체 실패가 파이프라인을 멈추면 안 됨


# ── 메타(마지막 업데이트) ───────────────────────────────────
def set_meta(key: str, value: str):
    client().table("meta").upsert(
        {"key": key, "value": value}, on_conflict="key").execute()


def get_meta(key: str) -> str | None:
    try:
        res = client().table("meta").select("value").eq("key", key).execute()
        return res.data[0]["value"] if res.data else None
    except Exception:
        return None


# ── 대시보드용 조회 ─────────────────────────────────────────
def load_stocks() -> list[dict]:
    res = client().table("stocks").select("*").execute()
    return res.data or []


def load_history(limit: int = 500) -> list[dict]:
    res = (client().table("history").select("*")
           .order("change_date", desc=True).limit(limit).execute())
    return res.data or []


# ── 관심가 (stock_targets) ──────────────────────────────────
# 사용자 입력 관심가의 영구저장. 수집/분류 파이프라인과 독립. 종목당 1개(symbol PK).
def get_targets() -> dict[str, float]:
    """stock_targets 전체를 {symbol: target_price(float)} 로 반환.
    데이터가 없거나 조회 실패 시 빈 dict(기존 get_* 안전 처리 스타일)."""
    try:
        res = client().table("stock_targets").select("symbol,target_price").execute()
        out = {}
        for r in (res.data or []):
            v = _num(r.get("target_price"))
            sym = r.get("symbol")
            if sym and v is not None:
                out[str(sym)] = v
        return out
    except Exception:
        return {}


def set_target(symbol: str, target_price: float) -> None:
    """관심가 upsert(symbol 기준). 0 이하/None 이면 저장하지 않고 삭제(해제)로 처리.
    created_at 은 DB default(now()) 유지, updated_at 만 갱신."""
    if target_price is None or float(target_price) <= 0:
        delete_target(symbol)
        return
    payload = {
        "symbol": str(symbol),
        "target_price": float(target_price),
        "updated_at": dt.datetime.utcnow().isoformat(),
    }
    client().table("stock_targets").upsert(payload, on_conflict="symbol").execute()


def delete_target(symbol: str) -> None:
    """해당 symbol 의 관심가 삭제(해제 버튼용)."""
    client().table("stock_targets").delete().eq("symbol", str(symbol)).execute()


# ── 매매 기록 (trade_records) ────────────────────────────────
# 국장/미장 × 대기중/진입/TP IN/완료. 레버리지 환산가는 저장하지 않고 화면에서 계산.
def list_trade_records(market_group: str | None = None,
                       status: str | None = None):
    """매매 기록 목록. 필터(market_group=KR/US, status=waiting/entered/tp_in/completed).
    조회 실패(테이블 미존재 등) 시 None 반환 — 호출측이 생성 안내를 띄운다.
    데이터가 없으면 빈 list."""
    try:
        q = client().table("trade_records").select("*")
        if market_group:
            q = q.eq("market_group", market_group)
        if status:
            q = q.eq("status", status)
        res = q.order("record_date", desc=True).execute()
        return res.data or []
    except Exception:
        return None


def code_by_name(name: str):
    """한국 종목명 정확일치 → 코드 (stocks 테이블, 유일 일치일 때만). read-only.
    대시보드 kr_code_by_name과 동일 규칙 — 파이프라인이 이름으로 저장된 본주를
    코드로 해소해 중복 수집/무의미한 이름 조회를 피하는 데 쓴다."""
    try:
        res = client().table("stocks").select("code").eq("name", str(name).strip()).execute()
        if res.data and len(res.data) == 1:
            return res.data[0]["code"]
    except Exception:
        pass
    return None


_ACTIVE_TRADE_STATUSES = ("waiting", "entered", "tp_in")


def get_active_trade_symbols():
    """활성(waiting/entered/tp_in) 매매기록의 market_group/symbol/leverage_symbol만
    조회한다(완료 기록 제외 — load_active_trades와 동일한 '활성' 정의). read-only.
    수집 대상 산출용이며, 실패(테이블 미존재 등) 시 빈 리스트."""
    try:
        res = (client().table("trade_records")
               .select("market_group,symbol,leverage_symbol")
               .in_("status", list(_ACTIVE_TRADE_STATUSES)).execute())
        return res.data or []
    except Exception:
        return []


def upsert_trade_record(rec: dict):
    """id가 있으면 update, 없으면 insert. 반환: record id(신규 insert 시 DB 생성값)."""
    payload = dict(rec)
    payload["updated_at"] = dt.datetime.utcnow().isoformat()
    rid = payload.pop("id", None)
    if rid:
        client().table("trade_records").update(payload).eq("id", str(rid)).execute()
        return rid
    res = client().table("trade_records").insert(payload).execute()
    return (res.data or [{}])[0].get("id")


def delete_trade_record(record_id) -> None:
    client().table("trade_records").delete().eq("id", str(record_id)).execute()


def get_latest_price(symbol: str):
    """본주/ETF 최신 가격: stocks.close 우선 → prices 최신 close → None(안전)."""
    try:
        res = client().table("stocks").select("close").eq("code", str(symbol)).execute()
        if res.data and res.data[0].get("close") is not None:
            return float(res.data[0]["close"])
        res = (client().table("prices").select("close").eq("code", str(symbol))
               .order("date", desc=True).limit(1).execute())
        if res.data and res.data[0].get("close") is not None:
            return float(res.data[0]["close"])
    except Exception:
        pass
    return None


def get_latest_quote(symbol: str):
    """본주/ETF 최신 가격 + 기준일: stocks(close, data_date) 우선 → prices(close, date) → None.
    get_latest_price 와 같은 우선순위에 기준일(as_of)만 더한 read-only 조회."""
    try:
        res = (client().table("stocks").select("close,data_date")
               .eq("code", str(symbol)).execute())
        if res.data:
            v = _num(res.data[0].get("close"))
            if v is not None and v > 0:
                return {"price": v, "as_of": res.data[0].get("data_date")}
        res = (client().table("prices").select("close,date").eq("code", str(symbol))
               .order("date", desc=True).limit(1).execute())
        if res.data:
            v = _num(res.data[0].get("close"))
            if v is not None and v > 0:
                return {"price": v, "as_of": res.data[0].get("date")}
    except Exception:
        pass
    return None


def get_common_close_pair(sym_a: str, sym_b: str, lookback: int = 10):
    """본주·ETF 두 종목의 prices 에서 최신 공통 거래일 close 쌍 (read-only).
    반환 (date, close_a, close_b), 공통 거래일이 없거나 조회 실패면 None."""
    from app.quotes import latest_common_close
    try:
        rows_a = (client().table("prices").select("date,close")
                  .eq("code", str(sym_a)).order("date", desc=True)
                  .limit(lookback).execute()).data or []
        rows_b = (client().table("prices").select("date,close")
                  .eq("code", str(sym_b)).order("date", desc=True)
                  .limit(lookback).execute()).data or []
        return latest_common_close(rows_a, rows_b)
    except Exception:
        return None


def _num(x):
    try:
        if x is None:
            return None
        v = float(x)
        return None if v != v else v   # NaN → None (JSON 직렬화 안전)
    except Exception:
        return None
