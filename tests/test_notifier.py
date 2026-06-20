"""
tests/test_notifier.py — 알림 메시지 빌더 및 전송 실패 처리
실제 전송은 하지 않는다(mock).
"""
from app import notifier


def _changes(ns=0, bs=0, nh=0):
    mk = lambda n: [{"name": f"종목{i}", "avg_6m": 800 * 10**8, "reason": "x"} for i in range(n)]
    return {"new_swing": mk(ns), "back_to_sector": mk(bs), "new_hold": mk(nh)}


def test_daily_message_with_changes():
    msg = notifier.build_daily("2026-06-20", "16:45", _changes(2, 1, 0), 47, 1)
    assert "신규 단기스윙 편입: 2종목" in msg
    assert "기존 섹터 복귀: 1종목" in msg
    assert "전체 단기스윙종목: 47개" in msg


def test_daily_message_no_change():
    msg = notifier.build_daily("2026-06-20", "16:45", _changes(0, 0, 0), 47, 0)
    assert "오늘 분류 변경 없음" in msg
    assert "전체 단기스윙종목: 47개" in msg


def test_error_message():
    msg = notifier.build_error("2026-06-20 16:45", "수집", "타임아웃", "3회 실패", "2026-06-19 16:45")
    assert "오류" in msg and "타임아웃" in msg and "2026-06-19 16:45" in msg


def test_send_failure_returns_false(monkeypatch):
    # 토큰 없음 → 전송 시도 없이 False
    monkeypatch.setattr(notifier.config, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(notifier.config, "TELEGRAM_CHAT_ID", "")
    monkeypatch.setattr(notifier.config, "NOTIFY_CHANNEL", "telegram")
    assert notifier.send("test") is False
