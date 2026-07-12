"""quotes.py — 본주·레버리지 ETF 가격 쌍 일관성 모듈 (순수 로직, Streamlit 의존 없음).

원칙: 본주와 ETF 가격은 동일 provider + 동일 기준일(as_of) 쌍으로만 환산에 사용한다.
서로 다른 공급자·날짜를 섞은 환산은 QuotePair.is_consistent=False 로 거부한다.
이 모듈은 DB에 쓰지 않는다(외부 조회 결과 포함).
"""
from __future__ import annotations
import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True)
class QuoteSnapshot:
    """한 종목의 가격 스냅샷: 심볼 · 가격 · 공급자(provider) · 기준일(as_of)."""
    symbol: str
    price: float | None
    provider: str | None
    as_of: str | None

    def is_valid(self) -> bool:
        try:
            return self.price is not None and float(self.price) > 0
        except (TypeError, ValueError):
            return False


@dataclass(frozen=True)
class QuotePair:
    """본주(base)·레버리지 ETF(leverage) 가격 쌍. is_consistent=True 일 때만 환산 허용."""
    base: QuoteSnapshot | None
    leverage: QuoteSnapshot | None
    provider: str | None
    as_of: str | None
    is_consistent: bool
    reason: str = ""


def make_pair(base: QuoteSnapshot | None, leverage: QuoteSnapshot | None) -> QuotePair:
    """스냅샷 두 개로 QuotePair 생성. 일관성 조건:
    두 스냅샷 모두 유효(가격>0) + provider 동일 + as_of 존재·동일."""
    def _fail(reason: str) -> QuotePair:
        return QuotePair(base=base, leverage=leverage, provider=None, as_of=None,
                         is_consistent=False, reason=reason)
    if base is None or not base.is_valid():
        return _fail("본주 가격 없음")
    if leverage is None or not leverage.is_valid():
        return _fail("ETF 가격 없음")
    if base.provider != leverage.provider:
        return _fail("가격 출처 불일치")
    if not base.as_of or base.as_of != leverage.as_of:
        return _fail("가격 기준일 불일치")
    return QuotePair(base=base, leverage=leverage, provider=base.provider,
                     as_of=base.as_of, is_consistent=True)


def _valid_close_map(rows) -> dict:
    """[{date, close}, ...] → {date: close} (close 가 양수 유효값인 행만)."""
    out = {}
    for r in (rows or []):
        d = r.get("date")
        v = r.get("close")
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if d and v == v and v > 0:      # NaN 제외
            out[d] = v
    return out


def latest_common_close(rows_a, rows_b):
    """두 종목의 prices 행 목록에서 최신 공통 거래일의 close 쌍을 고른다.
    반환 (date, close_a, close_b), 공통 거래일이 없으면 None."""
    map_a, map_b = _valid_close_map(rows_a), _valid_close_map(rows_b)
    common = set(map_a) & set(map_b)
    if not common:
        return None
    d = max(common)
    return (d, map_a[d], map_b[d])


FDR_PROVIDER = "FDR"


def fetch_fdr_snapshot(symbol) -> QuoteSnapshot | None:
    """FDR에서 한 종목의 최신 종가 스냅샷 조회 (외부 네트워크 — 버튼 클릭 시에만 호출).
    실패하면 None. 결과를 DB에 저장하지 않는다."""
    if not symbol:
        return None
    try:
        import FinanceDataReader as fdr
        end = dt.date.today()
        df = fdr.DataReader(str(symbol),
                            (end - dt.timedelta(days=14)).isoformat(), end.isoformat())
        if df is not None and len(df) and "Close" in df.columns:
            s = df["Close"].dropna()
            if len(s):
                v = float(s.iloc[-1])
                if v > 0:
                    ix = s.index[-1]
                    as_of = ix.date().isoformat() if hasattr(ix, "date") else str(ix)
                    return QuoteSnapshot(symbol=str(symbol), price=v,
                                         provider=FDR_PROVIDER, as_of=as_of)
    except Exception:
        pass
    return None


def fetch_fdr_pair(base_symbol, etf_symbol) -> QuotePair | None:
    """FDR에서 본주·ETF 한 쌍 조회. 둘 다 실패하면 None,
    아니면 make_pair 로 일관성 판정된 QuotePair (as_of 불일치면 is_consistent=False)."""
    base = fetch_fdr_snapshot(base_symbol)
    etf = fetch_fdr_snapshot(etf_symbol)
    if base is None and etf is None:
        return None
    return make_pair(base, etf)
