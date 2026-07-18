# CURRENT_TASK — 현재 활성 작업

> 이 문서는 **덮어쓰기** 문서다. 새 작업 시작 시 기존 내용을 누적하지 말고
> 아래 템플릿 전체를 새로 채운다. 작업이 없으면 상태를 `대기`로 둔다.

## 상태
검수 (구현·로컬 검증 완료 — commit·push 대기)

## 작업 — 카드 접힘 UX 단독 릴리스 (30일 로그인 제거)
- 브랜치: `feature/trade-card-collapse-only` (기준 staging/ui-v3=`d7540f3`)
- 결정: **카드 접힘 UX는 릴리스에 포함**, **30일 로그인은 완전 제거**.
  동작하지 않는 인증 코드를 운영에 남기지 않는다.

### 카드 접힘 UX — 검증 완료 (보존)
- 모든 매매 카드 기본 접힘 — 한 줄 요약행(`**ticker** · 날짜 · 상태 · 시장 ·
  2× ETF/본주 · chevron`) 전체가 터치 영역(tertiary 버튼, width="stretch").
- 펼침 상태는 `trade_expanded_record_ids`(record UUID str의 set) — 다중 동시
  펼침, 순서 변경 안전, 삭제 시 정리, 새 record 기본 접힘, 가격 갱신·수정
  저장 rerun 후 유지. 펼친 본문은 기존 상세·수정·삭제·가격 기능 그대로.
- `가격 새로고침` 버튼의 인라인 st.rerun() → on_click 콜백 수정 **보존**
  (기존에 상단 rerun이 시장/상태 라디오를 초기화하던 문제 해결).
- staging 실기기 검증 전 항목 통과(2026-07-19).

### 30일 로그인 — Community Cloud 제약으로 보류 (코드 제거)
- 원인(staging 실측으로 확정): 브라우저 cookie 생성·보존은 정상이지만
  **Streamlit Community Cloud edge proxy가 custom cookie를 앱 컨테이너의
  WebSocket handshake로 전달하지 않아** `st.context.cookies`에 이름 자체가
  도달하지 않음. 브라우저(Safari) 문제 아님 — Chromium probe에서도 동일.
  로컬(직접 서빙)에서는 동일 코드가 완전 동작했음.
- 제거: app/auth_session.py, tests/test_auth_session.py, config의
  APP_SESSION_SECRET, dashboard의 cookie component·토큰 복원·로그아웃 흐름 전부.
- **APP_SESSION_SECRET은 사용하지 않는다** — staging Secrets에 입력된 값은
  제거 대상(사용자가 Secrets에서 직접 삭제).
- 후속 후보(별도 과제): ① Streamlit native OIDC(st.login) ② 자체 호스팅
  (예: Fly.io — 프록시 없는 직접 서빙이면 cookie 방식 재사용 가능).

### 현재 운영 인증 정책
- 기존 비밀번호(APP_PASSWORD) + `st.session_state["authed"]` 단순 gate로 복원
  (운영 검증된 원형 그대로, 로그아웃 버튼 없음 — 원상복귀가 최소 변경).
- 같은 Streamlit 세션 내 rerun(저장·가격 조회·시장/상태 탭 이동)에서는
  로그인 유지, 새 브라우저 세션에서는 재로그인.

## 로컬 검증 결과 (2026-07-19)
- 전체 pytest 결과·금지 문자열 0건·로컬 Streamlit 검증은 보고 참조.
- 무변경: app/toss.py·toss_relay_client·toss_overlay·services/toss_relay·
  database.py·계산식·가격 우선순위·requirements·schema/CSV·Fly.

## DB write 허용 여부
아니오 (읽기 전용 — 로컬 검증은 stub, DB 접근 0회)

## push 허용 여부
아니오 — 사용자 검토·승인 후 commit/push.
