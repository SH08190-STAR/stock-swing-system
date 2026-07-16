# CURRENT_TASK — 현재 활성 작업

> 이 문서는 **덮어쓰기** 문서다. 새 작업 시작 시 기존 내용을 누적하지 말고
> 아래 템플릿 전체를 새로 채운다. 작업이 없으면 상태를 `대기`로 둔다.

## 상태
검수  <!-- 대기 / 설계 / 구현 / 검수 / push 대기 / 완료 -->

## 목표 — Toss Relay US-only gate (국장 화면 Relay 호출 차단)
> 배경: staging 활성 경로 실검증에서 US TP IN·US 진입은 provider Toss 정상,
> 국장(진입) 화면은 Relay 502 + fallback 안내 표시. 원인: 게이트에 market 필터가
> 없어 KR batch(숫자 코드 5개 + **한글 종목명 4개**)가 그대로 Relay→Toss로
> 전송됨. KR Toss 지원 형식은 미검증 — 정책: US만 활성, KR·미지의 시장은
> fail-closed 우회(기존 Supabase/FDR 유지, 실패 안내도 미표시).

- 브랜치: feature/toss-relay-us-only (기준 staging/ui-v3=9d60937)
- 변경(2파일, +119/−10):
  - dashboard/app.py — `TOSS_RELAY_MARKET="US"` 상수 +
    `_maybe_apply_toss_overlay(records, market_group)` 시그니처 확장.
    **market gate가 최우선**(toss_enabled 검사·심볼 수집·cache·lazy import·
    session_state·안내보다 먼저): `market_group != "US"`면(미지정·미지 값 포함)
    즉시 False. 호출부(render_trade_tab)가 market_group 전달. US 활성 로직·
    cache key·오류 처리·우선순위는 무변경.
  - tests/test_toss_overlay.py — 신규 10건(KR+설정존재 시 전 경로 0회·한글/숫자
    심볼 payload 차단·비정규 시장 6종 fail-closed·KR lazy import 0·US↔KR 전환
    격리·stale US overlay에도 KR 계산은 DB 경로). 기존 게이트 테스트 3곳은
    "US" 명시로 갱신(계약 유지).
- 무변경: app/toss.py·toss_relay_client·toss_overlay·config·relay 서버·
  database·기존 toss/relay 테스트·requirements·Dockerfile·workflows.
  KR ticker 변환·whitelist·특정 종목명 예외 처리 없음.
- 배포 특성: **Streamlit 전용 변경 — Fly Relay 재배포 불필요**(staging push만).

## 검증 결과 (로컬, 2026-07-16)
- py_compile OK. toss 4개 파일 178 passed(기존 168 + 신규 10).
- 전체 pytest **363 passed**(직전 353 + 10, .tmp/pytest.log). 회귀 0.
- git diff --check clean. 실 네트워크·DB 접근 0회.

## DB write 허용 여부
아니오 (읽기 전용 — DB 접근 없음)

## push 허용 여부
아니오 (commit·push 금지 — 사용자 승인 대기)
