"""toss_overlay.py — Toss 현재가(TossPrice)를 기존 QuoteSnapshot/QuotePair 계약으로
변환하는 순수 selection·conversion·consistency 로직 (Streamlit·DB·네트워크 비의존).

캐싱·TossClient 수명·session_state·화면 표시는 dashboard/app.py가 담당한다.
이 모듈은 부작용이 없고, 실패를 예외가 아닌 None 반환으로 표현해 호출측이
기존 Supabase 공통일자 QuotePair로 fallback하도록 한다.

원칙:
- Decimal 가격·각 종목의 개별 timestamp를 그대로 보존한다(같은 batch라는 이유로
  기준시각을 통일하지 않는다).
- 레버리지 쌍은 본주·ETF **둘 다 Toss**일 때만 성립 — 출처를 섞지 않는다.
- provider = "Toss".
"""
from __future__ import annotations

from app.quotes import QuoteSnapshot, QuotePair

TOSS_PROVIDER = "Toss"
DEFAULT_MAX_SKEW_SEC = 300          # 본주·ETF 기준시각 허용 차이(5분)


def is_configured(client_id, client_secret) -> bool:
    """두 credential이 모두 있을 때만 True. 미설정은 오류가 아니라 비활성 상태다."""
    return bool(str(client_id or "").strip()) and bool(str(client_secret or "").strip())


def collect_visible_symbols(records, resolve) -> list[str]:
    """화면에 보이는 매매기록에서 본주·레버리지 심볼을 순서 유지·중복 제거로 모은다.
    resolve(symbol, market_group) → 조회용 정규화 심볼(대시보드 _resolve_symbol 주입).
    빈 leverage_symbol은 제외한다."""
    out: list[str] = []
    seen = set()
    for r in (records or []):
        mg = r.get("market_group")
        for key in ("symbol", "leverage_symbol"):
            raw = r.get(key)
            if not raw:
                continue
            s = str(resolve(raw, mg) or "").strip().upper()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
    return out


def _valid(tp) -> bool:
    """TossPrice 유효성: 가격 양수 + timestamp가 timezone-aware."""
    if tp is None:
        return False
    price = getattr(tp, "last_price", None)
    ts = getattr(tp, "timestamp", None)
    try:
        if price is None or not (price > 0):
            return False
    except TypeError:
        return False
    if ts is None or getattr(ts, "tzinfo", None) is None or ts.tzinfo.utcoffset(ts) is None:
        return False
    return True


def _snap(tp) -> QuoteSnapshot:
    """TossPrice → QuoteSnapshot. Decimal 가격 유지, as_of는 종목별 원본 timestamp."""
    return QuoteSnapshot(symbol=tp.symbol, price=tp.last_price,
                         provider=TOSS_PROVIDER,
                         as_of=tp.timestamp.isoformat(timespec="seconds"))


def _lookup(overlay, symbol):
    return (overlay or {}).get(str(symbol or "").strip().upper())


def pick_single(overlay, symbol) -> QuoteSnapshot | None:
    """본주 단독: overlay에 유효한 Toss 가격이 있으면 QuoteSnapshot, 없으면 None(→DB)."""
    tp = _lookup(overlay, symbol)
    if not _valid(tp):
        return None
    return _snap(tp)


def pick_pair(overlay, base_symbol, etf_symbol, max_skew_sec=DEFAULT_MAX_SKEW_SEC):
    """레버리지 쌍: 본주·ETF 둘 다 유효 + 기준시각 차이 max_skew_sec 이하일 때만
    provider='Toss'인 consistent QuotePair를 만든다.
    하나라도 누락/무효/skew 초과면 None → 호출측이 쌍 전체를 DB로 fallback한다.
    (본주 Toss + ETF DB 같은 출처 혼합을 원천 차단)."""
    b = _lookup(overlay, base_symbol)
    e = _lookup(overlay, etf_symbol)
    if not _valid(b) or not _valid(e):
        return None
    skew = abs((b.timestamp - e.timestamp).total_seconds())
    if skew > max_skew_sec:
        return None
    sb, se = _snap(b), _snap(e)          # 각 종목 timestamp 원본 보존(as_of 개별)
    return QuotePair(base=sb, leverage=se, provider=TOSS_PROVIDER,
                     as_of=sb.as_of, is_consistent=True)
