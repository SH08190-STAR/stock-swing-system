"""
classifier.py — 6개월 일평균 거래대금 계산 + 단기스윙 분류 판정

규칙(요구사항 그대로)
- 최근 6개월 일평균 거래대금 = 실제 거래일 거래대금 합계 ÷ 실제 거래일 수
- 1,000억 원 "이하"  → 단기스윙 (정확히 1,000억도 단기스윙)
- 1,000억 원 "초과"  → 기존 산업 섹터 유지
- 데이터 불완전/누락 → 임의 분류 금지, "확인 보류(hold)"
- 한국 종목에만 적용. 해외는 분류 고정.
"""
from __future__ import annotations
import datetime as dt
from dateutil.relativedelta import relativedelta

from app import config


def _avg_6m_value(df, end: dt.date):
    """
    6개월 일평균 거래대금 계산.
    - end 로부터 6개월 전 날짜 이후의 실제 거래일만 사용
    - 거래대금이 결측이거나 0(거래정지 등)인 날은 평균에서 제외
    반환: (avg, used_days, total_value, today_value, short_avg, estimated)
    estimated=True 면 FDR 근사값이 섞였다는 뜻(주의 표시용)
    """
    start = end - relativedelta(months=config.LOOKBACK_MONTHS)

    d = df.copy()
    # 인덱스를 date 로 정규화
    d.index = [ix.date() if hasattr(ix, "date") else ix for ix in d.index]
    d = d[[ix >= start for ix in d.index]]

    if "value" not in d.columns or len(d) == 0:
        return None

    vals = d["value"].dropna()
    vals = vals[vals > 0]          # 0원(거래정지일 등) 제외
    used = len(vals)
    if used == 0:
        return None

    total = float(vals.sum())
    avg = total / used

    # 당일 거래대금(가장 최근 거래일)
    today_value = float(d["value"].iloc[-1]) if len(d) else None

    # 최근 20거래일 평균(대시보드 표시용)
    short = d["value"].dropna()
    short = short[short > 0].tail(config.SHORT_WINDOW_DAYS)
    short_avg = float(short.mean()) if len(short) else None

    estimated = bool(d["value_estimated"].any()) if "value_estimated" in d.columns else False

    return {
        "avg_6m": avg,
        "used_days": used,
        "total_value": total,
        "today_value": today_value,
        "short_avg": short_avg,
        "estimated": estimated,
        "close": float(d["close"].iloc[-1]) if "close" in d.columns and len(d) else None,
        "prev_close": float(d["close"].iloc[-2]) if "close" in d.columns and len(d) > 1 else None,
    }


def classify_one(collected: dict, end: dt.date) -> dict:
    """
    수집 결과 1건 → 분류 판정 1건.
    collected: collector.fetch_stock / collect_all 의 항목
    """
    base = {
        "code": collected["code"],
        "name": collected["name"],
        "market": collected["market"],
        "origin_sector": collected.get("origin_sector", ""),
        "origin_sub": collected.get("origin_sub", ""),
        "tier": collected.get("tier", ""),
        "data_date": end.isoformat(),
    }

    # 수집 자체가 보류면 그대로 보류
    if collected["status"] != "ok" or collected.get("ohlcv") is None:
        base.update({
            "classification": "hold",
            "avg_6m": None, "used_days": 0, "today_value": None,
            "short_avg": None, "close": None, "change_pct": None,
            "estimated": False,
            "reason": collected.get("reason", "데이터 누락"),
        })
        return base

    stat = _avg_6m_value(collected["ohlcv"], end)
    if stat is None:
        base.update({
            "classification": "hold",
            "avg_6m": None, "used_days": 0, "today_value": None,
            "short_avg": None, "close": None, "change_pct": None,
            "estimated": False,
            "reason": "유효 거래일 0 (거래정지/신규상장 가능)",
        })
        return base

    # 거래일 수가 비정상적으로 적으면(신규상장 등) 보류 처리
    # 6개월이면 보통 110~125 거래일. 30일 미만이면 평균 신뢰도 낮음.
    if stat["used_days"] < 30:
        base.update({
            "classification": "hold",
            "avg_6m": round(stat["avg_6m"]),
            "used_days": stat["used_days"],
            "today_value": stat["today_value"],
            "short_avg": stat["short_avg"],
            "close": stat["close"],
            "change_pct": _chg(stat),
            "estimated": stat["estimated"],
            "reason": f"거래일 부족({stat['used_days']}일) — 신규상장/거래정지 의심",
        })
        return base

    # 정상 판정: 1,000억 이하 → 단기스윙, 초과 → 기존섹터
    is_swing = stat["avg_6m"] <= config.SWING_THRESHOLD_KRW
    base.update({
        "classification": "swing" if is_swing else "sector",
        "avg_6m": round(stat["avg_6m"]),
        "used_days": stat["used_days"],
        "today_value": round(stat["today_value"]) if stat["today_value"] else None,
        "short_avg": round(stat["short_avg"]) if stat["short_avg"] else None,
        "close": stat["close"],
        "change_pct": _chg(stat),
        "estimated": stat["estimated"],
        "reason": "FDR 근사 거래대금 포함 — 참고용" if stat["estimated"] else "",
    })
    return base


def _chg(stat):
    if stat.get("close") and stat.get("prev_close"):
        return round((stat["close"] - stat["prev_close"]) / stat["prev_close"] * 100, 2)
    return None


def classify_all(collected_list: list[dict], end: dt.date) -> list[dict]:
    return [classify_one(c, end) for c in collected_list]


def diff_classifications(prev: dict[str, str], current: list[dict]) -> dict:
    """
    이전 분류(code→classification)와 현재를 비교해 변경 산출.
    반환: {"new_swing": [...], "back_to_sector": [...], "new_hold": [...]}
    """
    new_swing, back_to_sector, new_hold = [], [], []
    for c in current:
        code = c["code"]
        now = c["classification"]
        before = prev.get(code)
        if before == now:
            continue
        if now == "swing" and before in (None, "sector"):
            new_swing.append(c)
        elif now == "sector" and before == "swing":
            back_to_sector.append(c)
        elif now == "hold" and before != "hold":
            new_hold.append(c)
    return {"new_swing": new_swing, "back_to_sector": back_to_sector, "new_hold": new_hold}


def fmt_krw(v) -> str:
    """원 단위 정수를 '약 870억 원' 형태로."""
    if v is None:
        return "—"
    eok = v / 100_000_000
    if eok >= 10000:
        return f"약 {eok/10000:.2f}조 원"
    return f"약 {eok:,.0f}억 원"
