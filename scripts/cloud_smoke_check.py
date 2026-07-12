#!/usr/bin/env python
"""Streamlit Cloud 배포 후 smoke check (stdlib만 사용 — CI에서 추가 설치 불필요).

동작:
  1. 배포 대기: health endpoint가 200을 줄 때까지 --deploy-timeout 동안 폴링
  2. 안정성 검사(옵션): --stability-minutes 동안 --interval 간격으로 반복 확인,
     연속 실패가 --fail-threshold 에 도달하면 실패

실패 시 UTC 시각 / HTTP 상태 / 연속 실패 수를 기록한다.
secret 보호: URL의 query/fragment(토큰 포함 가능)는 출력하지 않는다.
종료코드: 0 = 통과, 1 = 실패, 2 = 인자 오류.

사용:
    py -3.12 scripts/cloud_smoke_check.py --url https://<app>.streamlit.app
    py -3.12 scripts/cloud_smoke_check.py --url <URL> --stability-minutes 10
"""
from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

HEALTH_PATH = "/_stcore/health"


def redact_url(url: str) -> str:
    """query/fragment를 제거한 표시용 URL (secret 노출 방지)."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def health_url(base_url: str) -> str:
    """앱 URL을 health endpoint URL로 정규화한다."""
    base = base_url.strip().rstrip("/")
    if urlsplit(base).path.endswith(HEALTH_PATH):
        return base
    return base + HEALTH_PATH


def fetch_status(url: str, timeout: int = 10) -> int | None:
    """HTTP 상태코드를 반환. 연결 실패는 None."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, OSError):
        return None


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
