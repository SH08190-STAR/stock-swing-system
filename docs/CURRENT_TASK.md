# CURRENT_TASK — 현재 활성 작업

> 이 문서는 **덮어쓰기** 문서다. 새 작업 시작 시 기존 내용을 누적하지 말고
> 아래 템플릿 전체를 새로 채운다. 작업이 없으면 상태를 `대기`로 둔다.

## 상태
검수 (구현·로컬 테스트 완료 — commit·push 대기)

## 작업 — 매매 카드 접힘형 목록 + 모바일 30일 로그인 유지
- 브랜치: `feature/trade-card-collapse-persistent-login` (기준 main=`46f4d41`)
- 범위: dashboard/app.py, app/auth_session.py(신규), app/config.py,
  tests/test_auth_session.py(신규), tests/test_trade_card_collapse.py(신규),
  .claude/launch.json(로컬 검증용 local-test 구성)

### 1) 매매 카드 접힘형 목록
- 모든 매매 카드는 기본 접힘 — 한 줄 요약(`**ticker** · 날짜 · 상태 · 시장 ·
  2× ETF/본주 · chevron`)만 표시. 요약행 전체가 st.button(type="tertiary",
  전체 폭) 터치 영역.
- 펼침 상태는 `st.session_state["trade_expanded_record_ids"]`(record id str의
  set)로 관리 — 다중 동시 펼침, 순서 변경·rerun에도 같은 카드 유지, 삭제 시
  해당 id 정리, 새 record 기본 접힘. 토글은 on_click 콜백(rerun 전 실행).
- 펼친 본문은 기존 카드 내용 그대로(_render_trade_card_body로 분리).
  수정·삭제는 기존 "기록 관리" 섹션 유지(무변경).
- 부수 수정: `가격 새로고침` 버튼을 인라인 st.rerun() → on_click 콜백으로 교체.
  기존 방식은 화면 상단에서 run을 중단시켜 아래쪽 시장/상태 라디오 위젯
  상태가 초기화되던 기존 동작(운영에도 존재) — 콜백으로 시장/상태·펼침 유지.

### 2) 30일 로그인 유지 (app/auth_session.py — components v2)
- 서명 토큰: `v1.<만료unix>.<HMAC-SHA256 base64url>`. 서명키는 도메인 구분 HMAC:
  `HMAC-SHA256(key=APP_SESSION_SECRET, msg=b"zpick-session-v1\x00"+APP_PASSWORD)`
  — 둘 중 하나만 바뀌어도 기존 토큰 전부 무효. 토큰에 비밀번호·기기정보 없음.
  검증: strict base64url decode + compare_digest + 만료가 30일+300초를 초과하는
  비정상 미래값 거부.
- 읽기: `st.context.cookies`(공식 API). 쓰기/삭제: **st.components.v2 component
  `zpick_cookie_action` 1개**(모듈 로드 시 1회 등록, v1 API·외부 JS/CDN 미사용).
  동적 값은 JS 소스 포맷팅 없이 mount `data`로만 전달, JS가 cookie name·token
  charset 재검증, 완료 시 `setTriggerValue("completed", action)` 신호. cookie:
  `zpick_session`, Max-Age 30일, Path=/, SameSite=Lax, https에서 Secure,
  Domain 미지정. **HttpOnly는 Streamlit 구조상 불가**(브라우저 JS 설정 한계).
- 흐름: 모든 버튼·완료 콜백은 st.rerun() 직접 호출 0 — 위젯/완료 이벤트의
  자연 rerun만 사용(이벤트당 최대 1회). 로그아웃은 2단계: ①버튼 콜백이 인증
  해제+삭제 pending 기록 → 로그인 화면 전환 ②delete component가 cookie 삭제
  후 완료 콜백이 pending 정리(+done 마커로 재마운트 루프 차단, 중복 수신
  idempotent). 무효(만료·변조) cookie도 같은 경로로 삭제(원본 token 비출력).
  cookie set 실패 시 세션 로그인은 유지(30일 유지만 미동작).
- `APP_SESSION_SECRET` 미설정·UTF-8 32바이트 미만 → 30일 유지만 비활성(기존
  세션 로그인 fallback, crash 없음, secret 이름·값 화면 비노출).

### 로컬 검증 결과 (2026-07-18, components v2 전환 후)
- 전체 pytest **404 passed** (기존 363 + 카드 13 + 인증 28, 회귀 0).
- 신규 버튼은 width="stretch"(deprecated use_container_width 신규 사용 0),
  components.v1/iframe/st.html 사용 0 — 소스 검사 테스트로 고정.
- 로컬 Streamlit(stub DB — Supabase/FDR/Relay 호출 0회): health 200, 7분+ 생존,
  traceback·segfault 0, v1 deprecation 경고 0(남은 use_container_width 경고는
  기존 코드의 것). 로그인→cookie 발급(만기 정확히 +30일)→새로고침·프로세스
  재시작 후 자동 복원→카드 다중 펼침→가격 새로고침 후 시장/상태/펼침 유지→
  로그아웃 2단계(delete 완료 후 cookie 삭제 확인)→새로고침 후 로그인 화면 유지→
  재로그인→변조 토큰 거부(+무효 cookie 자동 삭제)→모바일 375px 접힘·다중
  펼침·가로 overflow 없음 확인.
- 실제 30일 지속성·모바일 Safari 실기기 복원은 staging 수동 검증 항목.

### 배포 전 필요 절차 (사용자)
- Streamlit Cloud Secrets에 `APP_SESSION_SECRET` 추가(예: 로컬에서
  `py -3.12 -c "import secrets; print(secrets.token_urlsafe(48))"` 생성값).
  미설정이어도 앱은 기존 방식으로 동작(30일 유지만 비활성).

## 이번 단계 제한 — 하지 않음
- commit·push, main/staging 이동, Streamlit/Fly Secrets 변경, 배포·Reboot,
  DB write, 실제 Toss/Relay 호출.

## DB write 허용 여부
아니오 (읽기 전용 — 이번 로컬 검증은 DB 접근 자체 0회, stub 사용)

## push 허용 여부
아니오 — 사용자 검토·승인 후 commit/push.
