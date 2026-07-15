# CURRENT_TASK — 현재 활성 작업

> 이 문서는 **덮어쓰기** 문서다. 새 작업 시작 시 기존 내용을 누적하지 말고
> 아래 템플릿 전체를 새로 채운다. 작업이 없으면 상태를 `대기`로 둔다.

## 상태
검수  <!-- 대기 / 설계 / 구현 / 검수 / push 대기 / 완료 -->

## 목표 — Toss 시세 전용 Relay 서비스 foundation (Fly.io static egress)
> 배경: Streamlit Community Cloud outbound IP 수가 토스 허용 IP 한도(10개)를
> 초과해 **직접 Toss API 호출 방식은 폐기**. 일부 IP만 등록하는 불안정한 방식
> 금지. 고정 outbound IP를 가진 **Fly.io Relay(Tokyo nrt, shared-cpu-1x 256MB
> 1대 상시 실행, app-scoped static egress IPv4 1개만 토스에 등록)** 방식 채택.

- 브랜치: feature/toss-relay-service (기준 feature/toss-live-overlay-fix1=e25046e)
- 이번 범위(코드·테스트·배포 문서·CI까지만):
  - services/toss_relay/ — FastAPI Relay (main.py·config.py·전용 requirements·
    Dockerfile·fly.toml.example·README.md), app/toss.py TossClient 재사용(복제 없음)
  - 전용 requirements: fastapi·starlette·uvicorn·pydantic·requests 5개를
    로컬 검증 통과 조합으로 정확히 고정(==). Streamlit·pandas·supabase 등 미포함.
  - Dockerfile base = python:3.12.8-slim-bookworm(patch·Debian 고정), 비root
    uid 10001, 명시적 최소 COPY, PYTHONPATH=/srv, worker 1. + 루트 .dockerignore.
  - 공개 endpoint 정확히 2개: GET /healthz(무인증·Toss 미호출),
    POST /v1/prices(Bearer RELAY_SHARED_SECRET, 심볼 1~200개 문자열만)
  - tests/test_toss_relay.py 49건(실 네트워크 0회) +
    .github/workflows/toss-relay-tests.yml(신규 2 job: relay-tests +
    docker-build-health[healthz만 검증·secret 로그 비노출 검사], 기존 tests.yml 무변경)
- 제외 범위(아직 미실행): Fly 앱 생성·flyctl 인증·결제·실배포·egress IP 할당·
  토스 허용 IP 변경·실 credentials 입력·실 Toss 호출·Streamlit Secrets 변경·
  dashboard 연동. **실제 배포·실호출 전 상태.**

## Security boundary
- Toss credentials(TOSS_CLIENT_ID/SECRET)는 향후 **Relay(Fly secrets)에만** 존재.
  Streamlit에는 TOSS_RELAY_URL/TOSS_RELAY_TOKEN만 입력 예정.
- Relay 인증: Authorization Bearer + hmac.compare_digest(상수 시간),
  secret 32자 미만이면 시작 실패, 모든 인증 실패는 동일한 일반 401.
- 오류 응답은 error code + 고정 문구만 — 상류 본문·예외 repr·token·secret 비노출.
  Cache-Control: no-store, CORS 미허용, docs/openapi 비활성(그 외 endpoint 404).
- TossClient는 프로세스당 1개 lazy 생성(uvicorn worker 1·Machine 최대 1대 정책),
  import·healthz만으로 토큰 발급 없음. 주문·계좌 API 접근 기능 없음(추가 금지).

## 검증 결과 (로컬, 2026-07-16)
- py_compile OK. tests/test_toss_relay.py 49 passed(외부 socket 차단 fixture).
- test_toss.py + test_toss_overlay.py 63 passed(무변경 유지).
- 전체 pytest **297 passed**(기존 248 + relay 49, .tmp/pytest.log). 회귀 없음.
- workflow YAML·fly.toml.example TOML 문법 검증 OK. git diff --check clean.
- 보호 파일(dashboard·app/toss·requirements·tests.yml 등) 무변경 확인.
- Docker build/health: 로컬에 Docker 미설치 → GitHub Actions docker-build-health
  job에서 build + healthz 200 + 로그 secret 비노출을 검증(가짜 credential,
  /v1/prices 미호출로 실 Toss 네트워크 0회).

## DB write 허용 여부
아니오 (읽기 전용 — DB 연결 없음)

## push 허용 여부
아니오 (commit·push 금지 — 사용자 승인 대기)
