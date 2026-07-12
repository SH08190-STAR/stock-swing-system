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


# --- resolve_health: 리다이렉트 추적/분류 ---

APP = "app.example"
HEALTH = f"https://{APP}/_stcore/health"


def make_get(mapping):
    """url -> (status, location) 매핑을 따르는 가짜 GET. 없으면 (404, None)."""
    def get(url):
        return mapping.get(url, (404, None))
    return get


def test_resolve_health_immediate_200():
    get = make_get({HEALTH: (200, None)})
    r = smoke.resolve_health(HEALTH, get, APP)
    assert r.ok is True
    assert r.reason == "ok"
    assert r.final_status == 200


def test_resolve_health_303_then_200_revisits_health():
    # health 303 → 중간 경로 303 → health 재방문 시 (쿠키 세팅 후) 200.
    # URL 재방문을 루프로 오판하지 않아야 한다 (실제 Streamlit 부트스트랩 패턴).
    step = f"https://{APP}/-/login"
    calls = {"n": 0}

    def get(url):
        if url == HEALTH:
            calls["n"] += 1
            return (303, step) if calls["n"] == 1 else (200, None)
        if url == step:
            return (303, HEALTH)
        return (404, None)

    r = smoke.resolve_health(HEALTH, get, APP)
    assert r.ok is True
    assert r.first_status == 303
    assert r.final_status == 200


def test_resolve_health_uses_get_not_head():
    req = smoke.build_get_request(HEALTH)
    assert req.get_method() == "GET"


def test_resolve_health_redirect_loop_fails():
    a = f"https://{APP}/a"
    b = f"https://{APP}/b"
    get = make_get({HEALTH: (303, a), a: (303, b), b: (303, a)})
    r = smoke.resolve_health(HEALTH, get, APP)
    assert r.ok is False
    assert r.reason == "redirect_loop"


def test_resolve_health_auth_page_fails():
    login = f"https://{APP}/-/login"
    get = make_get({HEALTH: (303, login), login: (200, None)})
    r = smoke.resolve_health(HEALTH, get, APP)
    assert r.ok is False
    assert r.reason == "auth_redirect"
    assert r.final_status == 200


def test_resolve_health_external_domain_fails():
    ext = "https://share.streamlit.io/-/auth/app"
    get = make_get({HEALTH: (303, ext), ext: (200, None)})
    r = smoke.resolve_health(HEALTH, get, APP)
    assert r.ok is False
    assert r.reason == "external_redirect"


def test_resolve_health_external_then_back_succeeds():
    # 외부(share.streamlit.io)를 경유하지만 앱 호스트로 되돌아와 200 → 성공
    ext = "https://share.streamlit.io/-/auth/app"
    get = make_get({HEALTH: (303, ext), ext: (303, HEALTH + "x"),
                    HEALTH + "x": (200, None)})
    r = smoke.resolve_health(HEALTH, get, APP)
    assert r.ok is True
    assert r.reason == "ok"


def test_resolve_health_timeout_fails():
    get = make_get({HEALTH: (None, None)})
    r = smoke.resolve_health(HEALTH, get, APP)
    assert r.ok is False
    assert r.reason == "timeout"
    assert r.final_status is None


def test_resolve_health_bad_status_fails():
    get = make_get({HEALTH: (500, None)})
    r = smoke.resolve_health(HEALTH, get, APP)
    assert r.ok is False
    assert r.reason == "bad_status"
    assert r.final_status == 500


# --- classify_status: HealthResult → 폴링 정수 ---

def test_classify_status_ok_is_200():
    assert smoke.classify_status(smoke.HealthResult(True, "ok", final_status=200)) == 200


def test_classify_status_timeout_is_none():
    assert smoke.classify_status(smoke.HealthResult(False, "timeout", final_status=None)) is None


def test_classify_status_auth_200_is_not_200():
    # 최종 200이지만 auth/외부로 거부된 경우 200으로 취급하지 않는다
    assert smoke.classify_status(
        smoke.HealthResult(False, "external_redirect", final_status=200)
    ) == -1


def test_classify_status_bad_status_passthrough():
    assert smoke.classify_status(
        smoke.HealthResult(False, "bad_status", final_status=503)
    ) == 503
