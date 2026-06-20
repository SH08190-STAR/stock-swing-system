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

    # 오늘이 거래일이 아니면(주말/공휴일) 스킵
    if end != today_kst:
        # 단, 장 마감 직후가 아니라 '오늘이 휴장'인 경우만 스킵.
        # end가 과거이고 오늘이 주말/공휴일이면 갱신 불필요.
        if today_kst.weekday() >= 5 or end < today_kst:
            print(f"오늘({today_kst})은 휴장 또는 마감 전 — 최근 거래일 {end}. 스킵.")
            # 휴장일엔 조용히 종료(알림 X). 필요하면 아래 주석 해제.
            # notifier.send(f"휴장일({today_kst}) — 갱신 스킵")
            return

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

    # 6~7) 저장
    saved_days = 0
    fail_targets = []
    for c, raw in zip(results, collected):
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
