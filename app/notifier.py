"""
notifier.py — 메신저 알림 (기본: 텔레그램, 교체 가능)

알림 종류
1) 일일 요약  : 신규 편입/복귀/보류 + 전체 단기스윙 수 + 대시보드 링크
2) 변경 없음  : 오늘 변경 없음 + 전체 수 + 완료/오류 여부
3) 오류 알림  : 관리자에게 오류 시각/대상/원인/재시도/마지막 정상시각

NOTIFY_CHANNEL 환경변수로 telegram/discord/email/none 전환.
전송 실패해도 예외를 위로 던지지 않는다(파이프라인 중단 방지) — 실패는 True/False로 반환.
"""
from __future__ import annotations
import requests
from app import config
from app.classifier import fmt_krw


def _send_telegram(text: str) -> bool:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        print("[notifier] 텔레그램 토큰/chat_id 미설정 — 전송 생략")
        return False
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=15)
        return r.ok
    except Exception as e:
        print("[notifier] 텔레그램 전송 실패:", e)
        return False


def _send_discord(text: str) -> bool:
    if not config.DISCORD_WEBHOOK_URL:
        return False
    try:
        r = requests.post(config.DISCORD_WEBHOOK_URL, json={"content": text}, timeout=15)
        return r.status_code in (200, 204)
    except Exception as e:
        print("[notifier] 디스코드 전송 실패:", e)
        return False


def send(text: str) -> bool:
    ch = config.NOTIFY_CHANNEL
    if ch == "telegram":
        return _send_telegram(text)
    if ch == "discord":
        return _send_discord(text)
    if ch == "none":
        print("[notifier] 알림 비활성화\n" + text)
        return True
    # email 등은 필요 시 확장
    print("[notifier] 미지원 채널:", ch)
    return False


# ── 메시지 빌더 ─────────────────────────────────────────────
def build_daily(data_date: str, done_time: str, changes: dict,
                total_swing: int, hold_count: int) -> str:
    L = []
    L.append("📊 <b>한국주식 워치리스트 자동 업데이트</b>")
    L.append(f"기준일: {data_date}")
    L.append(f"업데이트 완료: {done_time}")
    L.append("")

    ns = changes["new_swing"]
    bs = changes["back_to_sector"]
    nh = changes["new_hold"]

    if not (ns or bs or nh):
        L.append("✅ 오늘 분류 변경 없음")
    else:
        if ns:
            L.append(f"🟢 신규 단기스윙 편입: {len(ns)}종목")
            for c in ns:
                L.append(f"  • {c['name']}: {fmt_krw(c.get('avg_6m'))}")
            L.append("")
        if bs:
            L.append(f"🔵 기존 섹터 복귀: {len(bs)}종목")
            for c in bs:
                L.append(f"  • {c['name']}: {fmt_krw(c.get('avg_6m'))}")
            L.append("")
        if nh:
            L.append(f"🟡 신규 확인 보류: {len(nh)}종목")
            for c in nh:
                L.append(f"  • {c['name']}: {c.get('reason','')}")
            L.append("")

    L.append(f"전체 단기스윙종목: {total_swing}개")
    L.append(f"데이터 오류/보류: {hold_count}개")
    L.append("")
    L.append(f"🔗 대시보드: {config.DASHBOARD_URL}")
    return "\n".join(L)


def build_error(occurred_at: str, target: str, cause: str,
                retried: str, last_ok: str | None) -> str:
    return "\n".join([
        "⚠️ <b>자동화 오류 발생</b>",
        f"시각: {occurred_at}",
        f"대상: {target}",
        f"원인: {cause}",
        f"재시도: {retried}",
        f"마지막 정상 업데이트: {last_ok or '기록 없음'}",
    ])


if __name__ == "__main__":
    # 전송 테스트 (토큰 설정돼 있으면 실제 발송)
    ok = send("✅ Z PICK notifier 테스트 메시지")
    print("전송 결과:", ok)
