# CURRENT_TASK — 현재 활성 작업

> 이 문서는 **덮어쓰기** 문서다. 새 작업 시작 시 기존 내용을 누적하지 말고
> 아래 템플릿 전체를 새로 채운다. 작업이 없으면 상태를 `대기`로 둔다.

## 상태
완료  <!-- 대기 / 설계 / 구현 / 검수 / push 대기 / 완료 -->

## 현재 작업 — Google OIDC 인증 Production 릴리스 (완료, 2026-07-22)
- main = Production = `44cd398`. 배포 전 main은 `91523e0`, ff-only 병합(merge commit 0개).
- Streamlit 1.58 공식 `st.login` / `st.user` / `st.logout` 기반 Google OIDC gate 운영 반영.
  30일 identity cookie는 Community Cloud 공식 OIDC 세션이 담당 —
  자체 cookie·component·브라우저 저장소·token 구현 0건.
- 상세 정책·운영 기준·롤백 절차는 docs/PROJECT_STATE.md
  "인증 정책 — Google OIDC 운영" 섹션을 정본으로 한다.

### Production 실화면 검증 (2026-07-22, 사용자 확인)
- Google 로그인 화면 정상, **APP_PASSWORD 화면 미노출**.
- 허용된 Google 계정 로그인 성공. `invalid_client`·`redirect_uri_mismatch`·
  `access_denied`·무한 redirect **없음**.
- 기존 앱 본문 정상, 기존 Supabase 데이터 정상 표시.
- 로그인 지속성(Chrome): 같은 탭 새로고침 유지 / 새 탭 유지 /
  모든 탭 종료 후 재접속 유지.
- 앱 내부 로그아웃: 즉시 Google 로그인 화면 전환, 보호 본문 미노출,
  같은 탭 새로고침·새 탭 접속 모두 재로그인 요구, **APP_PASSWORD fallback 없음**.
- 최종 재로그인 후 운영 상태 복구 완료.

### 기능 회귀 확인
- 기존 KPI·실데이터 정상, 국장↔미장 왕복 정상, Toss Relay 경고 없음.
- Authlib 오류·관리자 설정 오류·True/False 디버그 출력·traceback·segfault **없음**.

### 변경 파일 (91523e0 → 44cd398)
- `app/auth.py` (신규): 모드 판정·이메일 allowlist 순수 함수 (Streamlit 비의존)
- `app/config.py`: `AUTH_MODE`, `ALLOWED_GOOGLE_EMAILS` env 추가
- `dashboard/app.py`: `gate()` 모드 dispatch + `_password_gate()`(기존 보존) +
  `_oidc_gate()` (로그인 화면 / 미허용 차단 / 사이드바 소형 로그아웃)
- `requirements.txt`: `Authlib>=1.3.2` 추가
- `tests/test_auth_oidc.py` (신규), `tests/test_auth_gate.py` 보강
- 보호 파일 무변경: dashboard/database.py·app/toss*.py·services/toss_relay/**·
  schema/CSV·Dockerfile·workflows·Fly 설정.

### 검증 결과
- 전체 pytest **445 passed** (회귀 0). GitHub checks: tests·deploy-smoke success.
- Production 4분 smoke PASS(검사 17회·실패 0·bootstrap 303→final 200).
- DB migration·write 0, 실제 네트워크 호출 0.
  Secrets·Google Cloud·Fly는 이번 작업에서 추가 변경 없음.

### 취소된 로그아웃 핫픽스 (기록용)
- 사용자가 **Chrome/Google 계정 로그아웃**을 Z PICK 앱 내부 로그아웃으로 오해해
  "로그아웃 무반응"으로 보고됨.
- 이 오해를 전제로 `ff03e73`(로그아웃을 스크립트 본문 직접 호출로 변경) 핫픽스가
  생성됐으나 **Production main에는 병합하지 않았다.**
- 실제 Production 앱 내부 로그아웃은 기존 `44cd398`에서 정상 작동한다.
- staging은 `f32b86a` revert로 원복 — staging tree는 `44cd398`과 동일.
- `hotfix/oidc-logout`(ff03e73) 브랜치는 이력 보존용으로 남긴다.
- 내부 Streamlit 큐 경합 등 원인 가설은 **확정 원인으로 기록하지 않는다.**

## DB write 허용 여부
아니오 (읽기 전용)

## push 허용 여부
완료 — 이번 릴리스 관련 push는 모두 승인 후 수행됨.
추가 코드·Secrets·배포 변경은 신규 승인 대상.
