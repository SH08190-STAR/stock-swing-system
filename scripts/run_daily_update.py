"""
update.py — 일일 자동 갱신 파이프라인 (GitHub Actions가 호출)

순서(요구사항 그대로)
1. 거래일 판정 (휴장이면 종료)
2. 최신 일봉 수집
3. 6개월 범위 계산 + 일평균 거래대금
4. 단기스윙 분류 재판정
5. 이전 결과와 비교 → 신규/이탈/보류 산출
6. DB 저장 (일봉 upsert, 분류 upsert, 이력 insert)
7. 메타(최신화 시각) 갱신
8. 메신저 알림 (변경 있든 없든 발송)

오류가 나도 전체가 멈추지 않게 단계별 try로 감싸고, 관리자 알림을 보낸다.
"""
from __future__ import annotations
import os
import datetime as dt
import traceback

from app import config
from app import watchlist
from app import collector
from app import classifier
from app import database as db
from app import notifier


def now_kst_str() -> str:
    return (dt.datetime.utcnow() + dt.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M")


def calc_52w_high(ohlcv, end=None):
    """최근 365일 기준 52주 고점(장중 고가 max). 표시 캐시용 — 분류와 무관.
    - high 결측 행은 close 로 대체(구데이터 백필 전 과도기 안전)
    - 0/음수 제외, 52주 미만 데이터(신규상장)는 보유 기간 내 고점
    - 계산 불가/실패 시 None (개별 실패가 파이프라인을 멈추지 않게)"""
    try:
        if ohlcv is None or len(ohlcv) == 0:
            return None
        if end is None:
            end = dt.date.today()
        cutoff = end - dt.timedelta(days=365)
        idx = [ix.date() if hasattr(ix, "date") else ix for ix in ohlcv.index]
        mask = [d >= cutoff for d in idx]
        d = ohlcv[mask]
        if len(d) == 0:
            return None
        highs = d["high"] if "high" in d.columns else None
        closes = d["close"] if "close" in d.columns else None
        if highs is not None:
            highs = highs.where(highs > 0)   # 0/음수 고가는 결측 취급 → close 대체
        if highs is not None and closes is not None:
            s = highs.fillna(closes)
        elif highs is not None:
            s = highs
        elif closes is not None:
            s = closes
        else:
            return None
        s = s.dropna()
        s = s[s > 0]
        return float(s.max()) if len(s) else None
    except Exception:
        return None


def save_foreign(end, updated_at, last_ok=""):
    """
    해외 종목(표시용) 수집 후 기존 DB 구조에 저장.
    - 일봉: 기존 db.save_ohlcv 재사용(prices 테이블)
    - 현재가: 기존 db.save_classification 재사용, classification="global" 고정
      (해외는 분류 대상이 아니라 '표시 대상'. 한국 분류 로직과 혼동 방지용 고정값)
    - status!=ok / ohlcv 없음 / 0·None·NaN close 는 저장하지 않는다.
    반환: (저장 종목 수, 저장 일봉 행수). 호출측에서 try/except로 격리한다.
    """
    g_stocks = watchlist.all_global_stocks()
    foreign = collector.collect_foreign(g_stocks, end)
    f_days, f_rows = 0, []
    for r in foreign:
        if r.get("status") != "ok" or r.get("ohlcv") is None:
            continue
        close = r.get("close")
        if close is None or close != close or close <= 0:   # None / NaN / 0 제외
            continue
        try:
            f_days += db.save_ohlcv(r["code"], r.get("market", ""), r["ohlcv"])
        except Exception as e:
            db.log_error(f"해외일봉:{r['code']}", str(e), "건너뜀", last_ok)
        f_rows.append({
            "code": r["code"], "name": r.get("name", r["code"]),
            "market": r.get("market", ""),
            "origin_sector": r.get("origin_sector", ""),
            "classification": "global",      # 해외 = 표시 전용(분류 미적용)
            "close": close, "change_pct": r.get("change_pct"),
            "high_52w": calc_52w_high(r.get("ohlcv"), end),   # 52주 고점(실패 시 None)
            "estimated": True,               # FDR 근사 거래대금 포함
            "reason": "해외 표시용(분류 미적용)",
        })
    if f_rows:
        db.save_classification(f_rows, end.isoformat(), updated_at)
    return len(f_rows), f_days


def _looks_like_name(s: str) -> bool:
    """KRX 코드(6자리 ASCII 영숫자, 예: '005930'·'0193W0')가 아니면 종목명으로 간주.
    한글 등 비ASCII/길이 불일치는 이름 → FDR 티커 조회로는 해소 불가."""
    s = str(s or "").strip()
    if len(s) == 6 and s.isascii() and s.isalnum():
        return False
    return True


def watchlist_collected_codes() -> set:
    """이번 회차에 워치리스트로 이미 수집되는 code 집합(중복 fetch 방지용).
    KR 종목코드 + 해외 티커를 수집 정규화 규칙으로 통일한다."""
    codes = set()
    for s in watchlist.all_korean_stocks():
        c = collector.normalize_pipeline_symbol(s.get("code"), "KR")
        if c:
            codes.add(c)
    for s in watchlist.all_global_stocks():
        c = collector.normalize_pipeline_symbol(
            s.get("ticker") or s.get("code") or s.get("symbol"), "US")
        if c:
            codes.add(c)
    return codes


def save_trade_symbol_prices(end, updated_at, last_ok=""):
    """활성 trade_records의 본주·레버리지 심볼 중 워치리스트에 없는 것을 수집해
    prices 테이블에만 저장한다(stocks/classification 미변경 → 워치리스트 탭 노출 없음).
    - 본주와 ETF를 같은 회차·같은 end·같은 공급자 경로로 수집(동일 기준일 쌍 확보)
    - KR 코드는 한국 수집기, 미국 티커는 FDR 글로벌 수집기 사용
    - save_ohlcv는 on_conflict=code,date upsert라 같은 날짜 재실행에도 중복 행 없음
    - 개별 티커 실패는 격리(로그만 남기고 다음 진행), trade_records/stocks/stock_targets 무변경
    반환: {collected, saved_rows, skipped, failed, fail_codes}."""
    summary = {"collected": 0, "saved_rows": 0, "skipped": 0, "failed": 0,
               "unresolved": 0, "fail_codes": []}
    trade_rows = db.get_active_trade_symbols()
    targets = collector.build_trade_targets(trade_rows)
    already = watchlist_collected_codes()
    for mg, code in targets:
        # KR 본주는 종목명으로 저장된 경우가 많다 → 코드로 해소(대시보드와 동일 규칙).
        # 이름→코드가 워치리스트에 있으면 이미 수집된 것이라 스킵, 해소 실패한 순수
        # 이름(코드 아님)은 FDR로 조회해도 404이므로 미해소로 집계하고 건너뛴다.
        fetch_code = code
        if mg == "KR" and not code.isdigit():
            resolved = db.code_by_name(code)
            if resolved:
                fetch_code = str(resolved)
        if fetch_code in already:                 # 워치리스트에서 이미 수집됨 → 중복 fetch 방지
            summary["skipped"] += 1
            continue
        if mg == "KR" and not fetch_code.isdigit() and _looks_like_name(fetch_code):
            summary["unresolved"] += 1            # 코드로 해소 못 한 순수 종목명 — 조회 불가
            continue
        try:
            if mg == "KR":
                r = collector.fetch_stock(fetch_code, fetch_code, "", end)
            else:
                r = collector.fetch_foreign(fetch_code, fetch_code, "", end)
            if r.get("status") == "ok" and r.get("ohlcv") is not None:
                rows = db.save_ohlcv(code, r.get("market", ""), r["ohlcv"])   # prices만
                summary["collected"] += 1
                summary["saved_rows"] += rows
            else:
                summary["failed"] += 1
                summary["fail_codes"].append(code)
                db.log_error(f"매매심볼:{code}", r.get("reason") or "수집 실패", "건너뜀", last_ok)
        except Exception as e:
            summary["failed"] += 1
            summary["fail_codes"].append(code)
            db.log_error(f"매매심볼:{code}", str(e), "건너뜀", last_ok)
    return summary


def main():
    config.validate_for_collector()
    last_ok = db.get_meta("last_ok_update")

    # 1) 거래일 판정
    today_kst = (dt.datetime.utcnow() + dt.timedelta(hours=9)).date()
    end = collector.latest_trading_day(today_kst)
    if end is None:
        notifier.send(notifier.build_error(
            now_kst_str(), "거래일 판정", "최근 거래일 조회 실패",
            "pykrx·FDR 모두 실패", last_ok))
        print("거래일 판정 실패 — 종료")
        return

    # 오늘이 거래일이 아니면(주말/공휴일) 스킵. 단 FORCE_RUN=1이면 강제 진행(수동 테스트용).
    force = os.getenv("FORCE_RUN") == "1"
    if end != today_kst and not force:
        # 단, 장 마감 직후가 아니라 '오늘이 휴장'인 경우만 스킵.
        # end가 과거이고 오늘이 주말/공휴일이면 갱신 불필요.
        if today_kst.weekday() >= 5 or end < today_kst:
            print(f"오늘({today_kst})은 휴장 또는 마감 전 — 최근 거래일 {end}. 스킵.")
            # 휴장일엔 조용히 종료(알림 X). 필요하면 아래 주석 해제.
            # notifier.send(f"휴장일({today_kst}) — 갱신 스킵")
            return
    if force:
        print(f"FORCE_RUN — 거래일 판정 무시하고 최근 거래일 {end} 기준으로 강제 실행")

    print(f"기준 거래일: {end}")

    # 2~3) 수집 + 계산
    kr_stocks = watchlist.all_korean_stocks()
    try:
        collected = collector.collect_all(kr_stocks, end)
    except Exception as e:
        db.log_error("수집", str(e), "중단", last_ok)
        notifier.send(notifier.build_error(
            now_kst_str(), "데이터 수집", str(e), "중단", last_ok))
        print("수집 단계 치명적 오류:", e)
        return

    results = classifier.classify_all(collected, end)

    # 4~5) 이전 분류와 비교
    prev_class = db.get_prev_classifications()
    prev_avg = db.get_prev_avg()
    changes = classifier.diff_classifications(prev_class, results)

    # 6~7) 저장 (+ 52주 고점 계산 — 분류 결과에는 영향 없음, 표시 캐시)
    saved_days = 0
    fail_targets = []
    for c, raw in zip(results, collected):
        c["high_52w"] = calc_52w_high(raw.get("ohlcv"), end)   # 실패 시 None
        try:
            if raw.get("ohlcv") is not None:
                saved_days += db.save_ohlcv(c["code"], c["market"], raw["ohlcv"])
        except Exception as e:
            fail_targets.append(c["code"])
            db.log_error(f"일봉저장:{c['code']}", str(e), "건너뜀", last_ok)

    updated_at = now_kst_str()
    try:
        db.save_classification(results, end.isoformat(), updated_at)
        db.record_history(changes, prev_avg, end.isoformat())
        db.set_meta("last_ok_update", updated_at)
        db.set_meta("last_data_date", end.isoformat())
    except Exception as e:
        db.log_error("분류저장", str(e), "중단", last_ok)
        notifier.send(notifier.build_error(
            now_kst_str(), "DB 저장", str(e), "부분 실패", last_ok))

    # 통계
    total_swing = sum(1 for r in results if r["classification"] == "swing")
    hold_count = sum(1 for r in results if r["classification"] == "hold")

    # 8) 일일 알림 (변경 유무와 무관하게 발송)
    msg = notifier.build_daily(end.isoformat(), updated_at, changes,
                               total_swing, hold_count)
    notifier.send(msg)

    # 보류 종목이 많거나 저장 실패가 있으면 관리자 경고도 추가
    if fail_targets:
        notifier.send(notifier.build_error(
            now_kst_str(), f"일봉저장 {len(fail_targets)}종목",
            ",".join(fail_targets[:10]), "건너뜀(다음 회차 재시도)", updated_at))

    print(f"완료 — 단기스윙 {total_swing} / 보류 {hold_count} / 일봉 {saved_days}행 저장")
    print(f"변경: 신규 {len(changes['new_swing'])} / 복귀 {len(changes['back_to_sector'])} / 보류 {len(changes['new_hold'])}")

    # 9) 해외 종목(표시용) 수집·저장 — 분류 미적용. 전체/개별 실패해도 한국 결과를 유지한다.
    try:
        f_n, f_days = save_foreign(end, updated_at, last_ok)
        print(f"해외 표시용 저장 — 종목 {f_n} / 일봉 {f_days}행")
    except Exception as e:
        db.log_error("해외수집", str(e), "건너뜀", db.get_meta("last_ok_update"))
        print("해외 수집 단계 실패(한국 결과는 유지):", e)

    # 10) 매매기록 심볼(본주·레버리지 ETF) 가격 수집 — prices만 저장. 개별/전체 실패 격리.
    #     레버리지 거래가 DB 동일 기준일 쌍으로 자동 환산되게 하는 데이터 공급 단계.
    try:
        ts = save_trade_symbol_prices(end, updated_at, last_ok)
        print(f"매매 심볼 수집 — 수집 {ts['collected']} / 저장 {ts['saved_rows']}행 / "
              f"스킵 {ts['skipped']} / 미해소 {ts.get('unresolved', 0)} / 실패 {ts['failed']}")
        if ts["fail_codes"]:
            print("  실패 심볼:", ",".join(ts["fail_codes"][:20]))
    except Exception as e:
        db.log_error("매매심볼수집", str(e), "건너뜀", db.get_meta("last_ok_update"))
        print("매매 심볼 수집 단계 실패(다른 결과는 유지):", e)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        tb = traceback.format_exc()
        print(tb)
        try:
            notifier.send(notifier.build_error(
                now_kst_str(), "update.py 전체", tb[-500:], "중단",
                db.get_meta("last_ok_update")))
        except Exception:
            pass
        raise
