#!/usr/bin/env python
"""배포 전 로컬 검증 스크립트 (docs/DEPLOYMENT_GUARDRAILS.md 2단계).

검사 항목:
  1. git status        — 작업 트리 clean 여부
  2. secret 패턴       — 변경/신규 파일의 credential 노출, .env 추적 여부
  3. py_compile        — app/ dashboard/ scripts/ tests/ 컴파일
  4. 전체 테스트       — pytest -q
  5. requirements      — pip install --dry-run 으로 설치 가능 여부
  6. pip check         — 설치된 패키지 의존성 충돌
  7. Streamlit 서버    — 기동 → health 200 → 최소 120초 생존

긴 출력은 .tmp/predeploy_*.log 에 저장하고 콘솔에는 요약만 출력한다.
종료코드: 0 = 전체 통과, 1 = 하나 이상 실패.

사용:
    py -3.12 scripts/predeploy_check.py
    py -3.12 scripts/predeploy_check.py --skip-server        # 서버 검사 제외
    py -3.12 scripts/predeploy_check.py --survive-seconds 300
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP_DIR = ROOT / ".tmp"

SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}"), "sk- 형태 API key"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key 블록"),
    (
        re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
        "JWT 형태 토큰",
    ),
    (
        re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[=:]\s*['\"][^'\"\s]{12,}['\"]"),
        "하드코딩된 credential 할당",
    ),
]

SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".zip", ".xlsx", ".db", ".pyc"}
MAX_SCAN_BYTES = 1_000_000


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


def run_cmd(args: list[str], log_path: Path | None = None, timeout: int = 1800) -> tuple[int, str]:
    """명령을 실행하고 (returncode, stdout+stderr)를 반환. log_path에 전문 저장."""
    proc = subprocess.run(
        args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    if log_path is not None:
        log_path.write_text(output, encoding="utf-8")
    return proc.returncode, output


def find_secrets(text: str) -> list[str]:
    """텍스트에서 secret 패턴이 걸린 줄을 찾는다."""
    hits: list[str] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for pattern, label in SECRET_PATTERNS:
            if pattern.search(line):
                hits.append(f"line {lineno}: {label}")
                break
    return hits


def iter_scan_targets(porcelain: str) -> list[str]:
    """git status --porcelain 출력에서 secret 검사 대상 경로를 뽑는다 (삭제 제외)."""
    targets: list[str] = []
    for line in porcelain.splitlines():
        if len(line) < 4:
            continue
        status, path = line[:2], line[3:].strip().strip('"')
        if "D" in status:
            continue
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        targets.append(path)
    return targets


def check_git_status(allow_dirty: bool) -> tuple[CheckResult, str]:
    rc, porcelain = run_cmd(["git", "status", "--porcelain"])
    if rc != 0:
        return CheckResult("git status", False, "git status 실행 실패"), ""
    dirty = bool(porcelain.strip())
    if not dirty:
        return CheckResult("git status", True, "clean"), porcelain
    n = len(porcelain.strip().splitlines())
    if allow_dirty:
        return CheckResult("git status", True, f"미커밋 변경 {n}건 (--allow-dirty)"), porcelain
    return CheckResult("git status", False, f"미커밋 변경 {n}건 — 배포는 clean 트리에서"), porcelain


def check_secrets(porcelain: str) -> CheckResult:
    problems: list[str] = []
    _, tracked_env = run_cmd(["git", "ls-files", ".env"])
    if tracked_env.strip():
        problems.append(".env 파일이 git에 추적되고 있음")
    for rel in iter_scan_targets(porcelain):
        path = ROOT / rel
        if rel.startswith(".tmp") or not path.is_file():
            continue
        if path.suffix.lower() in SKIP_SUFFIXES or path.stat().st_size > MAX_SCAN_BYTES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        problems.extend(f"{rel} {hit}" for hit in find_secrets(text))
    log_path = TMP_DIR / "predeploy_secrets.log"
    log_path.write_text("\n".join(problems) or "no findings", encoding="utf-8")
    if problems:
        return CheckResult("secret 패턴", False, f"{len(problems)}건 의심 (상세: {log_path.name})")
    return CheckResult("secret 패턴", True)


def check_py_compile() -> CheckResult:
    dirs = [d for d in ("app", "dashboard", "scripts", "tests") if (ROOT / d).is_dir()]
    rc, _ = run_cmd(
        [sys.executable, "-m", "compileall", "-q", *dirs],
        log_path=TMP_DIR / "predeploy_compile.log",
    )
    return CheckResult("py_compile", rc == 0, "" if rc == 0 else "컴파일 오류 (predeploy_compile.log)")


def check_tests() -> CheckResult:
    rc, output = run_cmd(
        [sys.executable, "-m", "pytest", "-q"],
        log_path=TMP_DIR / "predeploy_pytest.log",
    )
    tail = output.strip().splitlines()[-1] if output.strip() else ""
    return CheckResult("전체 테스트", rc == 0, tail)


def check_requirements_installable() -> CheckResult:
    rc, _ = run_cmd(
        [sys.executable, "-m", "pip", "install", "--dry-run", "-q", "-r", "requirements.txt"],
        log_path=TMP_DIR / "predeploy_pip_dryrun.log",
    )
    return CheckResult(
        "requirements 설치 가능", rc == 0, "" if rc == 0 else "resolver 실패 (predeploy_pip_dryrun.log)"
    )


def check_pip_check() -> CheckResult:
    rc, output = run_cmd(
        [sys.executable, "-m", "pip", "check"],
        log_path=TMP_DIR / "predeploy_pip_check.log",
    )
    return CheckResult("pip check", rc == 0, output.strip().splitlines()[0] if output.strip() else "")


def http_status(url: str, timeout: int = 5) -> int | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, OSError):
        return None


def check_server(port: int, survive_seconds: int) -> CheckResult:
    """Streamlit 서버를 띄워 health 200과 최소 생존 시간을 확인한다."""
    name = "Streamlit 서버"
    log_path = TMP_DIR / "predeploy_streamlit.log"
    health = f"http://127.0.0.1:{port}/_stcore/health"
    with open(log_path, "w", encoding="utf-8") as log_file:
        proc = subprocess.Popen(
            [
                sys.executable, "-m", "streamlit", "run", "dashboard/app.py",
                "--server.port", str(port), "--server.headless", "true",
            ],
            cwd=ROOT,
            stdout=log_file,
            stderr=log_file,
        )
        try:
            deadline = time.monotonic() + 90
            up = False
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    return CheckResult(name, False, f"기동 실패 — 조기 종료 (log: {log_path.name})")
                if http_status(health) == 200:
                    up = True
                    break
                time.sleep(2)
            if not up:
                return CheckResult(name, False, f"90초 내 health 200 실패 (log: {log_path.name})")
            end = time.monotonic() + survive_seconds
            while time.monotonic() < end:
                time.sleep(5)
                if proc.poll() is not None:
                    return CheckResult(
                        name, False, f"{survive_seconds}초 생존 실패 — 도중 종료 (log: {log_path.name})"
                    )
                if http_status(health) != 200:
                    return CheckResult(name, False, f"생존 중 health 비정상 (log: {log_path.name})")
            return CheckResult(name, True, f"health 200, {survive_seconds}초 생존")
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()


def summarize(results: list[CheckResult]) -> str:
    lines = []
    for r in results:
        mark = "PASS" if r.ok else "FAIL"
        lines.append(f"[{mark}] {r.name}" + (f" — {r.detail}" if r.detail else ""))
    overall = all(r.ok for r in results)
    lines.append("결과: " + ("전체 통과 — 배포 진행 가능" if overall else "실패 항목 있음 — 배포 중단"))
    return "\n".join(lines)


def exit_code(results: list[CheckResult]) -> int:
    return 0 if all(r.ok for r in results) else 1


def main(argv: list[str] | None = None) -> int:
    # Windows cp949 콘솔에서 한글·특수문자 출력 오류 방지
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="배포 전 로컬 검증")
    parser.add_argument("--allow-dirty", action="store_true", help="미커밋 변경을 허용")
    parser.add_argument("--skip-tests", action="store_true", help="전체 테스트 생략")
    parser.add_argument("--skip-server", action="store_true", help="Streamlit 서버 검사 생략")
    parser.add_argument("--port", type=int, default=8599)
    parser.add_argument("--survive-seconds", type=int, default=120, help="최소 생존 시간 (기본 120)")
    args = parser.parse_args(argv)

    TMP_DIR.mkdir(exist_ok=True)
    results: list[CheckResult] = []

    git_result, porcelain = check_git_status(args.allow_dirty)
    results.append(git_result)
    results.append(check_secrets(porcelain))
    results.append(check_py_compile())
    if not args.skip_tests:
        results.append(check_tests())
    results.append(check_requirements_installable())
    results.append(check_pip_check())
    if not args.skip_server:
        results.append(check_server(args.port, args.survive_seconds))

    print(summarize(results))
    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
