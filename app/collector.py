"""
collector.py — 한국주식 일봉/거래대금 수집

설계 원칙
- 주 소스 pykrx, 예비 소스 FinanceDataReader. 한쪽이 막히면 자동 폴백.
- 사용자가 데이터를 직접 입력하지 않는다. 전부 외부 소스 자동 수집.
- 거래대금은 추정하지 않고 각 거래일의 "실제" 값을 사용.
- 데이터 누락/실패 시 0원 덮어쓰기·삭제 금지. 해당 종목은 status="hold"(확인 보류).
- 거래일 판정으로 휴장일엔 수집을 건너뛴다.

반환 형태(종목 1개):
{
  "code": "042700", "name": "한미반도체", "market": "KOSPI",
  "ohlcv": DataFrame(index=date, columns=[종가, 거래량, 거래대금]),  # 6개월치
  "status": "ok" | "hold",
  "reason": "" | "데이터 누락" 등,
}
"""
from __future__ import annotations
import time
import datetime as dt
import requests
from dateutil.relativedelta import relativedelta

from app import config

# pykrx / FDR 는 import 시점에 무거우므로 함수 안에서 지연 로딩
def _import_pykrx():
    from pykrx import stock
    return stock

def _import_fdr():
    import FinanceDataReader as fdr
    return fdr


# ── 거래일 판정 ─────────────────────────────────────────────
def latest_trading_day(today: dt.date | None = None) -> dt.date | None:
    """
    today(미지정 시 한국 오늘) 기준, 가장 최근 거래일을 반환.
    pykrx의 영업일 함수를 우선 사용하고, 실패하면 FDR로 폴백.
    오늘이 거래일이 아니면(주말/공휴일) 직전 거래일을 돌려준다.
    수집 가능한 거래일이 없으면 None.
    """
    if today is None:
        # 한국시간 기준 오늘
        today = (dt.datetime.utcnow() + dt.timedelta(hours=9)).date()

    # 1) pykrx: 가장 가까운 영업일
    try:
        stock = _import_pykrx()
        # get_nearest_business_day_in_a_week: 해당 날짜 기준 가장 가까운 영업일
        s = stock.get_nearest_business_day_in_a_week(today.strftime("%Y%m%d"))
        d = dt.datetime.strptime(s, "%Y%m%d").date()
        # 미래(오늘이 장 마감 전 등)면 한 주 앞에서 다시
        if d > today:
            s = stock.get_nearest_business_day_in_a_week(
                (today - dt.timedelta(days=1)).strftime("%Y%m%d"))
            d = dt.datetime.strptime(s, "%Y%m%d").date()
        return d
    except Exception:
        pass

    # 2) FDR 폴백: 코스피 지수 일봉에서 마지막 인덱스
    try:
        fdr = _import_fdr()
        start = (today - dt.timedelta(days=10)).strftime("%Y-%m-%d")
        idx = fdr.DataReader("KS11", start, today.strftime("%Y-%m-%d"))
        if len(idx) > 0:
            return idx.index[-1].date()
    except Exception:
        pass

    return None


def is_trading_day(day: dt.date) -> bool:
    """주어진 날짜가 실제 거래일인지."""
    ltd = latest_trading_day(day)
    return ltd == day


# ── 개별 종목 6개월 일봉 수집 ────────────────────────────────
def _fetch_pykrx(code: str, start: dt.date, end: dt.date):
    """pykrx로 일봉(거래대금 포함) 조회. 컬럼 표준화."""
    stock = _import_pykrx()
    df = stock.get_market_ohlcv(
        start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), code
    )
    if df is None or len(df) == 0:
        return None
    # pykrx 컬럼: 시가 고가 저가 종가 거래량 거래대금 등락률
    rename = {"종가": "close", "거래량": "volume", "거래대금": "value"}
    df = df.rename(columns=rename)
    keep = [c for c in ["close", "volume", "value"] if c in df.columns]
    df = df[keep].copy()
    # 거래정지 등으로 거래대금 0/결측인 날은 평균 계산에서 제외하도록 표시
    return df


def _to_float(x):
    """문자열/숫자를 float로. 쉼표·공백·None 안전 처리."""
    if x is None:
        return None
    try:
        return float(str(x).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _fetch_datagokr(code: str, start: dt.date, end: dt.date):
    """
    공공데이터포털 '금융위원회_주식시세정보'(getStockPriceInfo) API.

    pykrx/FDR이 거래대금을 주지 않게 된 환경에서 실제 거래대금(trPrc)을 제공하는
    공식 공공 API. config.DATA_GO_KR_KEY(무료 인증키)가 있어야 동작한다.
    응답 필드: basDt(기준일), srtnCd(단축코드), clpr(종가), trqu(거래량), trPrc(거래대금).
    """
    import pandas as pd

    if not config.DATA_GO_KR_KEY:
        return None

    url = ("https://apis.data.go.kr/1160100/service/"
           "GetStockSecuritiesInfoService/getStockPriceInfo")
    params = {
        "serviceKey": config.DATA_GO_KR_KEY,   # Decoding(일반) 인증키
        "numOfRows": 400,                       # 6개월 거래일(~125) 여유
        "pageNo": 1,
        "resultType": "json",
        "beginBasDt": start.strftime("%Y%m%d"),
        "endBasDt": end.strftime("%Y%m%d"),
        "likeSrtnCd": code,                     # 단축코드(부분일치) — 아래서 정확코드만 채택
    }
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()  # 키 오류 등으로 XML이 오면 여기서 예외 → 상위에서 폴백

    items = (data.get("response", {}).get("body", {}).get("items") or {})
    item = items.get("item") if isinstance(items, dict) else None
    if not item:
        return None
    if isinstance(item, dict):
        item = [item]

    recs = []
    for it in item:
        srtn = str(it.get("srtnCd", "")).zfill(6)
        if srtn != code:               # likeSrtnCd 부분일치로 섞인 다른 종목 제외
            continue
        bas = it.get("basDt")
        try:
            d = dt.datetime.strptime(str(bas), "%Y%m%d").date()
        except (ValueError, TypeError):
            continue
        recs.append({
            "date": d,
            "close": _to_float(it.get("clpr")),
            "volume": _to_float(it.get("trqu")),
            "value": _to_float(it.get("trPrc")),   # 실제 거래대금(추정 아님)
        })
    if not recs:
        return None

    df = pd.DataFrame(recs).set_index("date").sort_index()
    df["value_estimated"] = False
    return df


def _fetch_fdr(code: str, start: dt.date, end: dt.date):
    """
    FDR 폴백. FDR은 거래대금(value)을 직접 주지 않는 경우가 있어
    종가×거래량으로 근사한다. (주 소스 실패 시 비상용)
    """
    fdr = _import_fdr()
    df = fdr.DataReader(code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    if df is None or len(df) == 0:
        return None
    out = df.rename(columns={"Close": "close", "Volume": "volume"})
    out = out[["close", "volume"]].copy()
    if "Amount" in df.columns:      # 일부 버전은 거래대금 제공
        out["value"] = df["Amount"]
        out["value_estimated"] = False
    else:
        out["value"] = out["close"] * out["volume"]   # 근사
        out["value_estimated"] = True
    return out


def fetch_stock(code: str, name: str, market: str,
                end: dt.date) -> dict:
    """
    한 종목의 최근 6개월 일봉 수집. 주→예비 폴백, 재시도 포함.
    실패해도 예외를 던지지 않고 status="hold"로 돌려준다(자동화 중단 방지).
    """
    start = end - relativedelta(months=config.LOOKBACK_MONTHS)

    # 거래대금을 실제로 주는 공공 API 키가 있으면 최우선. 이어서 설정된 주/예비 소스.
    order = []
    if config.DATA_GO_KR_KEY:
        order.append("datagokr")
    for s in (config.PRIMARY_SOURCE, config.FALLBACK_SOURCE):
        if s not in order:
            order.append(s)

    dispatch = {
        "datagokr": _fetch_datagokr,
        "pykrx": _fetch_pykrx,
        "fdr": _fetch_fdr,
    }

    last_err = ""
    for source in order:
        fetch_fn = dispatch.get(source, _fetch_fdr)
        for attempt in range(config.MAX_RETRY):
            try:
                df = fetch_fn(code, start, end)
                if df is not None and len(df) > 0:
                    return {
                        "code": code, "name": name, "market": market,
                        "ohlcv": df, "source": source,
                        "status": "ok", "reason": "",
                    }
            except Exception as e:
                last_err = f"{source}: {type(e).__name__} {e}"
            time.sleep(config.REQUEST_SLEEP_SEC)

    # 모든 소스/재시도 실패 → 확인 보류 (이전 데이터는 호출측에서 보존)
    return {
        "code": code, "name": name, "market": market,
        "ohlcv": None, "source": "",
        "status": "hold", "reason": last_err or "데이터 누락",
    }


def collect_all(stocks: list[dict], end: dt.date) -> list[dict]:
    """
    워치리스트 한국 종목 전체 수집.
    stocks: watchlist.all_korean_stocks() 결과
    """
    results = []
    n = len(stocks)
    for i, s in enumerate(stocks, 1):
        r = fetch_stock(s["code"], s["name"], s["market"], end)
        # 원본 섹터 정보 이어붙임
        r["origin_sector"] = s.get("origin_sector", "")
        r["origin_sub"] = s.get("origin_sub", "")
        r["tier"] = s.get("tier", "")
        results.append(r)
        if i % 10 == 0 or i == n:
            ok = sum(1 for x in results if x["status"] == "ok")
            print(f"  수집 {i}/{n} (성공 {ok})")
    return results


if __name__ == "__main__":
    # 단독 실행: 거래일 + 종목 1개 테스트
    d = latest_trading_day()
    print("최근 거래일:", d)
    if d:
        r = fetch_stock("042700", "한미반도체", "KOSPI", d)
        print("상태:", r["status"], "| 소스:", r.get("source"))
        if r["ohlcv"] is not None:
            print(r["ohlcv"].tail(3))
