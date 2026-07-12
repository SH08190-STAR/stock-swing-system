#!/usr/bin/env python
"""Streamlit Cloud 배포 후 smoke check (stdlib만 사용 — CI에서 추가 설치 불필요).

동작:
  1. wake-up: base URL을 GET 1회 호출해 sleeping 앱을 깨운다
  2. 배포 대기: health endpoint가 최종 200이 될 때까지 --deploy-timeout 동안 폴링
  3. 안정성 검사(옵션): --stability-minutes 동안 --interval 간격으로 반복 확인,
     연속 실패가 --fail-threshold 에 도달하면 실패

health 판정:
  Streamlit Cloud는 첫 요청에서 share.streamlit.io로 303 → 세션 쿠키 세팅 →
  앱 호스트로 되돌린 뒤 최종 200을 준다. 따라서 GET(HEAD 아님)으로 리다이렉트를
  최대 5회까지 쿠키를 유지하며 따라가고, **최종 착지점**으로만 성공을 판정한다.
  303 자체는 성공으로 처리하지 않는다.
    - 성공: 최종 status 200 이고 최종 호스트가 앱 호스트와 동일
    - 실패: 리다이렉트 초과(루프) / 로그인·auth 페이지 / 외부 도메인 / 200 아님 / timeout

실패 시 UTC 시각 / HTTP 상태 / 연속 실패 수를 기록한다.
secret 보호: URL의 query/fragment(토큰 포함 가능)는 출력하지 않는다.
종료코드: 0 = 통과, 1 = 실패, 2 = 인자 오류.

사용:
    py -3.12 scripts/cloud_smoke_check.py --url https://<app>.streamlit.app
    py -3.12 scripts/cloud_smoke_check.py --url <URL> --stability-minutes 10
"""
from __future__ import annotations

import argparse
import http.cookiejar
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

HEALTH_PATH = "/_stcore/health"
REDIRECT_CODES = {301, 302, 303, 307, 308}
MAX_REDIRECTS = 5
USER_AGENT = "deploy-smoke/1.0"
# 최종 착지점이 이 경로 조각을 포함하면 로그인/auth 페이지로 간주(실패)
AUTH_HINTS = ("/login", "signin", "sign-in", "oauth")


def redact_url(url: str) -> str:
    """query/fragment를 제거한 표시용 URL (secret 노출 방지)."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def _host(url: str) -> str:
    return urlsplit(url).netloc


def _host_path(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.netloc}{parts.path}"


def health_url(base_url: str) -> str:
    """앱 URL을 health endpoint URL로 정규화한다."""
    base = base_url.strip().rstrip("/")
    if urlsplit(base).path.endswith(HEALTH_PATH):
        return base
    return base + HEALTH_PATH


def _looks_like_auth(url: str) -> bool:
    """최종 착지 경로가 로그인/인증 페이지로 보이는지 추정."""
    path = urlsplit(url).path.lower()
    return any(hint in path for hint in AUTH_HINTS)


def build_get_request(url: str) -> urllib.request.Request:
    """리다이렉트를 자동으로 따라가지 않는 단발 GET 요청 (HEAD 아님)."""
    return urllib.request.Request(url, method="GET", headers={"User-Agent": USER_AGENT})


def _make_single_get(timeout: int):
    """쿠키를 유지하며 리다이렉트를 따라가지 않는 GET 함수를 만든다.

    프로브 1회 동안 쿠키 jar를 공유해 Streamlit의 쿠키 부트스트랩이 완료되게 한다.
    반환 함수: get(url) -> (status|None, location|None), 연결 실패/timeout은 status=None.
    """

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
        _NoRedirect,
    )

    def get(url: str) -> tuple[int | None, str | None]:
        try:
            with opener.open(build_get_request(url), timeout=timeout) as resp:
                return resp.status, resp.headers.get("Location")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers.get("Location")
        except (urllib.error.URLError, OSError):
            return None, None

    return get


@dataclass
class HealthResult:
    ok: bool
    reason: str
    first_status: int | None = None
    first_location: str | None = None
    final_status: int | None = None
    final_host_path: str | None = None


def resolve_health(
    url: str,
    get,
    base_host: str,
    max_redirects: int = MAX_REDIRECTS,
) -> HealthResult:
    """GET으로 리다이렉트를 최대 max_redirects회 따라가 최종 결과를 판정한다.

    루프 판정은 max_redirects 초과로만 한다(부트스트랩이 health URL로 되돌아와
    재방문하는 것은 정상이므로 URL 재방문을 루프로 보지 않는다).
    auth/외부 판정은 최종 200 착지점에서만 한다(중간 홉은 따라간다).
    """
    current = url
    first_status: int | None = None
    first_location: str | None = None

    for hop in range(max_redirects + 1):
        status, location = get(current)
        if hop == 0:
            first_status = status
        if status is None:
            return HealthResult(False, "timeout", first_status, first_location,
                                None, _host_path(current))
        if status in REDIRECT_CODES:
            if not location:
                return HealthResult(False, "redirect_no_location", first_status,
                                    first_location, status, _host_path(current))
            newurl = urljoin(current, location)
            if hop == 0:
                first_location = redact_url(newurl)
            current = newurl
            continue
        if status == 200:
            if _host(current) != base_host:
                return HealthResult(False, "external_redirect", first_status,
                                    first_location, 200, _host_path(current))
            if _looks_like_auth(current):
                return HealthResult(False, "auth_redirect", first_status,
                                    first_location, 200, _host_path(current))
            return HealthResult(True, "ok", first_status, first_location,
                                200, _host_path(current))
        return HealthResult(False, "bad_status", first_status, first_location,
                            status, _host_path(current))

    # max_redirects 초과 = 루프 또는 과도한 체인
    return HealthResult(False, "redirect_loop", first_status, first_location,
                        None, _host_path(current))


def classify_status(result: HealthResult) -> int | None:
    """HealthResult를 폴링 루프용 정수 상태로 환원. 성공=200, 실패=200 아닌 값."""
    if result.ok:
        return 200
    if result.final_status is None:
        return None
    if result.final_status == 200:
        return -1  # auth/외부로 착지해 200이지만 거부된 경우
    return result.final_status


def log_health_result(result: HealthResult, log=print) -> None:
    """진단 1줄 출력 — query/secret 없이 status와 host/path만."""
    log(
        f"{utc_now_iso()} health "
        f"{'OK' if result.ok else 'FAIL:' + result.reason} "
        f"first={result.first_status} location={result.first_location or '-'} "
        f"final={result.final_status} at={result.final_host_path or '-'}"
    )


def fetch_status(url: str, timeout: int = 15, log=print) -> int | None:
    """리다이렉트를 따라가 health를 판정하고 폴링 루프용 정수 상태를 반환한다."""
    result = resolve_health(url, _make_single_get(timeout), _host(url))
    log_health_result(result, log)
    return classify_status(result)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Failure:
    at: str
    status: int | None
    consecutive: int


def wait_for_deploy(
    url: str,
    timeout_s: float,
    interval_s: float,
    fetch=fetch_status,
    sleep=time.sleep,
    clock=time.monotonic,
    log=print,
) -> bool:
    """health가 200이 될 때까지 대기. timeout_s 초과 시 False."""
    start = clock()
    attempt = 0
    while True:
        attempt += 1
        status = fetch(url)
        if status == 200:
            log(f"{utc_now_iso()} 배포 확인: attempt {attempt}에서 health 200")
            return True
        log(f"{utc_now_iso()} 배포 대기 중 (attempt {attempt}, status={status})")
        if clock() - start >= timeout_s:
            log(f"{utc_now_iso()} 배포 대기 시간 초과 ({timeout_s:.0f}s)")
            return False
        sleep(interval_s)


def run_stability(
    url: str,
    duration_s: float,
    interval_s: float,
    fail_threshold: int,
    fetch=fetch_status,
    sleep=time.sleep,
    clock=time.monotonic,
    log=print,
) -> tuple[bool, int, list[Failure]]:
    """duration_s 동안 health를 반복 확인. 연속 실패 fail_threshold 도달 시 실패.

    반환: (안정 여부, 총 검사 횟수, 실패 기록 목록)
    """
    start = clock()
    consecutive = 0
    checks = 0
    failures: list[Failure] = []
    while True:
        status = fetch(url)
        checks += 1
        if status == 200:
            consecutive = 0
        else:
            consecutive += 1
            failure = Failure(utc_now_iso(), status, consecutive)
            failures.append(failure)
            log(f"{failure.at} health 실패: status={status}, 연속 {consecutive}회")
            if consecutive >= fail_threshold:
                log(f"{utc_now_iso()} 연속 실패 {fail_threshold}회 도달 — 불안정 판정")
                return False, checks, failures
        if clock() - start >= duration_s:
            return True, checks, failures
        sleep(interval_s)


def main(argv: list[str] | None = None) -> int:
    # Windows cp949 콘솔에서 한글·특수문자 출력 오류 방지
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Streamlit Cloud smoke check")
    parser.add_argument("--url", required=True, help="앱 URL (query 등 secret은 출력되지 않음)")
    parser.add_argument("--deploy-timeout", type=float, default=600, help="배포 대기 한도 초 (기본 600)")
    parser.add_argument("--interval", type=float, default=15, help="확인 간격 초 (기본 15)")
    parser.add_argument(
        "--stability-minutes", type=float, default=0,
        help="배포 확인 후 안정성 검사 시간(분). 0이면 생략, 권장 10",
    )
    parser.add_argument("--fail-threshold", type=int, default=3, help="연속 실패 허용 횟수 (기본 3)")
    args = parser.parse_args(argv)

    if not args.url.lower().startswith(("http://", "https://")):
        print("오류: --url은 http(s):// 로 시작해야 함")
        return 2

    target = health_url(args.url)
    print(f"대상: {redact_url(target)}")

    # sleeping 앱을 깨우기 위해 base URL을 GET 1회 호출 (best-effort)
    base = args.url.strip().rstrip("/")
    print(f"wake-up GET: {redact_url(base)}")
    fetch_status(base)

    if not wait_for_deploy(target, args.deploy_timeout, args.interval):
        print("[FAIL] 배포 대기 실패 — health 200 미도달")
        return 1

    if args.stability_minutes > 0:
        ok, checks, failures = run_stability(
            target, args.stability_minutes * 60, args.interval, args.fail_threshold
        )
        if not ok:
            print(f"[FAIL] 안정성 검사 실패: 검사 {checks}회, 실패 {len(failures)}회")
            return 1
        print(
            f"[PASS] 안정성 {args.stability_minutes:g}분: 검사 {checks}회, "
            f"일시 실패 {len(failures)}회"
        )

    print("[PASS] smoke check 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
