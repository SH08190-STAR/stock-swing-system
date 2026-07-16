# CURRENT_TASK — 현재 활성 작업

> 이 문서는 **덮어쓰기** 문서다. 새 작업 시작 시 기존 내용을 누적하지 말고
> 아래 템플릿 전체를 새로 채운다. 작업이 없으면 상태를 `대기`로 둔다.

## 상태
검수  <!-- 대기 / 설계 / 구현 / 검수 / push 대기 / 완료 -->

## 목표 — Streamlit 직접 Toss 호출 → Relay 경유 전환 (mock 구현·로컬 검증)
> 배경: Fly Relay(nrt, app-scoped static egress IPv4 — 실제 앱 이름·IP는 tracked
> 파일에 기록하지 않음)가 배포·실조회 검증 완료(NVDA/NVDL 200 OK). 이제
> Streamlit이 Toss를 직접 호출하지 않고 Relay HTTPS를 경유하도록 배선을 교체한다.
> Streamlit 설정은 TOSS_RELAY_URL/TOSS_RELAY_TOKEN 두 개뿐 —
> TOSS_CLIENT_ID/SECRET은 Relay(Fly secrets)에만 존재한다.

- 브랜치: feature/toss-relay-streamlit-integration (기준 31062a8)
- 변경:
  - app/toss_relay_client.py 신규 — 순수 Relay HTTP 클라이언트(RelayPrice·
    TossRelay* 예외 계층·https 전용 URL 검증·token 최소 32자·Bearer 헤더 전용·
    200개 chunk·재시도 0·token/원본 body 비노출). endpoint는 /v1/prices 고정.
  - app/config.py — TOSS_CLIENT_ID/SECRET 제거, TOSS_RELAY_URL/TOSS_RELAY_TOKEN.
  - dashboard/app.py — _toss_client가 TossRelayClient 생성(lazy import),
    _fetch_toss_prices가 TossRelayError 격리. 게이트·캐시·우선순위 구조 무변경.
  - app/toss_overlay.py 무변경(속성 계약 duck-typing으로 RelayPrice 그대로 수용).
  - services/toss_relay/fly.toml.example — dockerfile 경로를 실배포 검증값
    "Dockerfile"(fly.toml 위치 기준)로 수정. 실제 fly.toml은 .gitignore 등록.
- Fix 1 계약(e25046e) 유지: Relay 설정이 없거나 한쪽만 있으면 client 생성·cache
  접근·심볼 수집·session_state 생성·app.toss_relay_client import(→requests) 전부
  0회 — 기존 _ext_quote→DB 경로와 동일. token은 cache 인자·key·session_state 금지.
- 우선순위: 수동 _ext_quote → Relay Toss(쌍은 둘 다 Toss + skew≤300초, 혼합 금지)
  → DB pair/quote → FDR(수동 버튼). 오류 시 전체 batch DB fallback + 안내 1회.
- 캐시: client는 cache_resource(프로세스 1개), 가격 batch는 cache_data ttl=20초.
  새로고침은 batch 캐시만 clear — client·relay token 유지, Toss OAuth는 Relay 소관.

## 검증 결과 (로컬, 2026-07-16)
- py_compile OK. tests/test_toss_relay_client.py 41 passed(신규, mock Session만).
- tests/test_toss_overlay.py 38 passed(기존 38개 계약을 Relay 설정으로 적응).
- test_toss.py 25 + test_toss_relay.py 49 passed(무변경 유지).
- 전체 pytest **338 passed**(직전 297 + 신규 41, .tmp/pytest.log). 회귀 없음.
- 실제 Relay/Toss 네트워크 호출 0회·DB write 0회.

## 이번 단계 제한 — 하지 않음
- Streamlit Secrets 입력·Relay 실호출·Toss 직접 호출·Fly 변경·
  main 병합·staging 이동·commit·push·DB write.

## DB write 허용 여부
아니오 (읽기 전용)

## push 허용 여부
아니오 (commit·push 금지 — 사용자 승인 대기)
