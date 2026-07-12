"""scripts/cloud_smoke_check.py 단위 테스트 (네트워크·실제 sleep 없음)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import cloud_smoke_check as smoke  # noqa: E402


class FakeClock:
    """sleep 호출이 시간을 전진시키는 가짜 시계."""

    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


def make_fetch(statuses):
    """상태 목록을 순서대로 반환하고 소진되면 마지막 값을 반복하는 fetch."""
    seq = list(statuses)

    def fetch(url):
        return seq.pop(0) if len(seq) > 1 else seq[0]

    return fetch


def test_health_url_appends_path():
    assert smoke.health_url("https://app.streamlit.app") == (
        "https://app.streamlit.app/_stcore/health"
    )
    assert smoke.health_url("https://app.streamlit.app/") == (
        "https://app.streamlit.app/_stcore/health"
    )


def test_health_url_keeps_existing_path():
    url = "https://app.streamlit.app/_stcore/health"
    assert smoke.health_url(url) == url


def test_redact_url_strips_query_and_fragment():
    out = smoke.redact_url("https://h.example/app/path?token=abc123#frag")
    assert out == "https://h.example/app/path"
    assert "abc123" not in out


def test_wait_for_deploy_succeeds_after_retries():
    clock = FakeClock()
    ok = smoke.wait_for_deploy(
        "u", timeout_s=600, interval_s=15,
        fetch=make_fetch([None, 503, 200]),
        sleep=clock.sleep, clock=clock.monotonic, log=lambda *_: None,
    )
    assert ok is True


def test_wait_for_deploy_times_out():
    clock = FakeClock()
    ok = smoke.wait_for_deploy(
        "u", timeout_s=60, interval_s=15,
        fetch=make_fetch([None]),
        sleep=clock.sleep, clock=clock.monotonic, log=lambda *_: None,
    )
    assert ok is False


def test_run_stability_all_healthy():
    clock = FakeClock()
    ok, checks, failures = smoke.run_stability(
        "u", duration_s=60, interval_s=15, fail_threshold=3,
        fetch=make_fetch([200]),
        sleep=clock.sleep, clock=clock.monotonic, log=lambda *_: None,
    )
    assert ok is True
    assert checks == 5  # 0,15,30,45,60초 시점
    assert failures == []


def test_run_stability_fails_on_consecutive_failures():
    clock = FakeClock()
    ok, checks, failures = smoke.run_stability(
        "u", duration_s=600, interval_s=15, fail_threshold=3,
        fetch=make_fetch([200, 500, 502, None]),
        sleep=clock.sleep, clock=clock.monotonic, log=lambda *_: None,
    )
    assert ok is False
    assert [f.consecutive for f in failures] == [1, 2, 3]
    assert [f.status for f in failures] == [500, 502, None]


def test_run_stability_consecutive_counter_resets():
    clock = FakeClock()
    ok, _, failures = smoke.run_stability(
        "u", duration_s=60, interval_s=15, fail_threshold=3,
        fetch=make_fetch([500, 200, 500, 200, 200]),
        sleep=clock.sleep, clock=clock.monotonic, log=lambda *_: None,
    )
    assert ok is True
    assert [f.consecutive for f in failures] == [1, 1]


def test_main_rejects_bad_url():
    assert smoke.main(["--url", "not-a-url"]) == 2
