# CURRENT_TASK — 현재 활성 작업

> 이 문서는 **덮어쓰기** 문서다. 새 작업 시작 시 기존 내용을 누적하지 말고
> 아래 템플릿 전체를 새로 채운다. 작업이 없으면 상태를 `대기`로 둔다.

## 상태
검수  <!-- 대기 / 설계 / 구현 / 검수 / push 대기 / 완료 -->

## 목표 — 토스증권 Open API client foundation (1차)
> 배경: UI/UX 3단계(3B~3D) 운영 검증 완료, LKG=39b8c95. 토스 Open API로
> 본주·레버리지 ETF 현재가를 화면 표시용 실시간 overlay로 반영하는 작업의
> 1차 단계 — **순수 클라이언트 모듈 + mock 테스트만** 구현한다.

- 브랜치: feature/toss-api-client-foundation (기준 main=39b8c95)
- 내용:
  1. `app/toss.py` 신규 — Streamlit 비의존 순수 모듈.
     - `TossClient(client_id, client_secret, session=, base_url=, now_fn=)`:
       생성자 주입, requests.Session 주입 가능, timeout (connect 3s, read 5s).
     - 인증: POST /oauth2/token (client_credentials, form-urlencoded).
       access_token/token_type("Bearer")/expires_in 검증. 인스턴스 내부 토큰 캐시,
       만료 5분 전 재발급, threading.Lock으로 중복 발급 방지(인스턴스당 토큰 1개).
     - 가격: GET /api/v1/prices — 심볼 정규화(공백·빈값 제거, 대문자, 입력 순서
       유지 중복 제거), 200개 단위 chunk, 반환 `dict[str, TossPrice]`
       (`TossPrice`: symbol · last_price=Decimal · currency · timestamp=aware datetime,
       종목별 timestamp 원본 보존 — batch라도 통일하지 않음).
       200 응답에서 누락된 심볼은 반환 dict에 넣지 않는다.
     - 오류: 첫 401 → 토큰 폐기 후 정확히 1회 재발급·재요청, 재차 401 →
       TossAuthError. 403 → TossForbiddenError. 429 → TossRateLimitError
       (retry_after 보존, 자동 sleep·재시도 없음). timeout → TossTimeoutError.
       5xx → TossApiError. JSON·필드·가격·timestamp 이상 → TossResponseError.
  2. `tests/test_toss.py` 신규 — mock Session만 사용, 실제 네트워크 호출 0회.
     토큰 발급/재사용/만료 margin/401 처리/403/404/429/timeout/5xx/응답 이상/
     batch·chunk·중복 제거·대문자화·Decimal·timestamp aware 보존/부분 누락/
     secret 비노출/동시 발급 방지 — 25건.
     경계조건: 전체 요청 404(부분 누락·재시도 없이 예외), naive timestamp 거부.

## 보안 정책 (절대)
- 이전에 화면 노출된 Client ID/Secret은 **재발급으로 폐기됨** — 절대 사용 금지.
- 새 credentials 값은 요청·출력·기록하지 않는다. 코드·테스트·로그·문서에
  실제 credentials/access token/Authorization 헤더 삽입 금지.
- 모든 예외 문자열은 고정 문구 + HTTP 상태코드만(요청 body·헤더·응답 본문 비포함).
  requests 예외는 `from None`으로 체인 차단. 모듈 내 print/log 없음.
- 운영 정책: 운영 앱만 credentials 상시 보유. 로컬·일반 스테이징은 mock만.
  최종 실호출 검증 시에만 스테이징에 임시 등록 후 삭제. 운영·스테이징 동시 사용 금지.
- 단일 Client/token 위험: 토스는 클라이언트당 활성 토큰 1개(재발급 시 이전 토큰
  즉시 무효) — 두 프로세스가 같은 credentials로 토큰을 발급하면 상호 무효화된다.

## 이번 단계 제한 (1차) — 하지 않음
- Toss API 실호출·IP 등록·환경변수 연결·Streamlit Secrets 연결.
- 대시보드(dashboard/app.py) 연결, app/config.py 수정, QuotePair 생성,
  fallback 연결 — 전부 2차.
- DB 연결·write 없음. requirements/schema/CSV/workflow 무변경.

## 수정 허용 파일 (1차)
- app/toss.py (신규)
- tests/test_toss.py (신규)
- docs/PROJECT_STATE.md
- docs/CURRENT_TASK.md

## 검증 결과 (로컬, 2026-07-15)
- py_compile app/toss.py OK. tests/test_toss.py 25 passed (mock만, 네트워크 0회).
- 전체 pytest: .tmp/pytest.log 참조 (기존 185 + 신규 25 = 210).
- git diff --check clean. 보호 파일(dashboard/app.py·app/config.py·requirements·
  schema·workflow) 무변경.

## DB write 허용 여부
아니오 (읽기 전용 — DB 연결 자체 없음)

## push 허용 여부
아니오 (commit·push 금지 — 사용자 승인 대기)
