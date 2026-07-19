# CURRENT_TASK — 현재 활성 작업

> 이 문서는 **덮어쓰기** 문서다. 새 작업 시작 시 기존 내용을 누적하지 말고
> 아래 템플릿 전체를 새로 채운다. 작업이 없으면 상태를 `대기`로 둔다.

## 상태
검수  <!-- 대기 / 설계 / 구현 / 검수 / push 대기 / 완료 -->

## 현재 작업 — Google OIDC 인증 전환 1차 (구현·로컬 검증 완료, 2026-07-19)
- 브랜치: `feature/google-oidc-auth` (base `91523e0`). **commit·push·deploy 미수행.**
- Streamlit 1.58 공식 `st.login` / `st.user` / `st.logout` 기반 Google OIDC gate 구현.
  30일 identity cookie는 Community Cloud 공식 OIDC 세션이 담당 —
  자체 cookie·component·브라우저 저장소·token 구현 0건.

### 인증 모드 전환 정책 (Secrets로만 제어)
- 설정 우선순위: **st.secrets(root) > 환경변수 > 기본값** (`auth.read_setting`)
- `AUTH_MODE` 미설정/`""` → password 모드 (**코드 선배포 시 Production 동작 불변** —
  운영은 APP_PASSWORD 설정 상태)
- `AUTH_MODE="password"` → APP_PASSWORD gate. **APP_PASSWORD 미설정·빈값·공백이면
  fail closed** (자동 통과 제거 — 비밀번호 입력창도 열지 않고 "관리자 인증 설정 오류"만)
- `AUTH_MODE="oidc"` → Google OIDC gate. APP_PASSWORD fallback 없음(오류 시에도 우회 불가).
  **[auth] preflight**: redirect_uri(절대 http/https + `/oauth2callback` 종료)·
  cookie_secret(UTF-8 32바이트 이상)·client_id·client_secret·server_metadata_url이
  전부 유효해야만 로그인 버튼·st.login 노출, 아니면 fail closed
  ("Google 로그인 설정 오류"만 — 누락 키·값 비노출)
- 그 외 값 → fail closed (보호 화면 없이 "관리자 설정 오류"만 표시)

### 허용 이메일 정책
- `ALLOWED_GOOGLE_EMAILS` canonical 형식은 **쉼표 구분 문자열 1개**
  (TOML 리스트도 파싱 지원). 실제 값은 staging Secrets에서만 설정 — repo 커밋 금지.
- strip+casefold 정규화 + 빈 항목·중복 제거 후 **정확 일치만** 허용.
  부분 일치·도메인 와일드카드 금지.
- allowlist 미설정·빈 목록 → fail closed. email claim 없음 → 거부.
- 미허용 계정: "허용되지 않은 Google 계정입니다" + 로그아웃(계정 변경) 버튼.
- gate는 `main()` 최상단 — 미로그인·미허용 시 DB/Relay/FDR/Toss/본문 진입 0.

### staging에 필요한 Secrets (값은 여기 기록하지 않음)
- `AUTH_MODE = "oidc"`
- `ALLOWED_GOOGLE_EMAILS = "<허용 이메일>"` (콤마 구분)
- `[auth]` 섹션: `redirect_uri = "https://<APP_URL>/oauth2callback"`,
  `cookie_secret`, `client_id`, `client_secret`,
  `server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"`
- **실제 Google Cloud OAuth client 설정은 미수행** — staging 수동 검증 항목.

### 변경 파일
- `app/auth.py` (신규): 모드 판정·이메일 allowlist 순수 함수 (Streamlit 비의존)
- `app/config.py`: `AUTH_MODE`, `ALLOWED_GOOGLE_EMAILS` env 추가
- `dashboard/app.py`: `gate()` 모드 dispatch + `_password_gate()`(기존 보존) +
  `_oidc_gate()` (로그인 화면 / 미허용 차단 / 사이드바 소형 로그아웃)
- `requirements.txt`: `Authlib>=1.3.2` 추가
- `tests/test_auth_oidc.py` (신규, 31개): 모드·allowlist·gate 흐름·보호 경계·password 회귀
- `.claude/launch.json`: 로컬 검증용 실행 구성(런타임 영향 없음)

### 검증 결과 (보안 하드닝 라운드 포함)
- 전체 pytest **439 passed** (기준 385 + 신규 54, 회귀 0). 기존
  auth/카드/Toss/Relay 테스트 전부 통과.
- 로컬 E2E(password 정상 설정): health 200, 로그인 화면, 오답 거부, 정답 통과,
  본문은 **stub DB로만 렌더**(실제 Supabase read 0). traceback·segfault 0.
- 로컬 E2E(APP_PASSWORD 누락): "관리자 인증 설정 오류" fail closed —
  비밀번호 입력창·본문 미노출.
- 로컬 E2E(oidc, `[auth]` 미설정): "Google 로그인 설정 오류" fail closed —
  로그인 버튼 미노출. 실제 Google redirect 로그인은 staging Secrets 설정 후 수동 검증.
- 로컬(잘못된 AUTH_MODE): fail closed 확인.
- **기존 DB 데이터 무변경** — migration 없음, user/email 컬럼 추가 없음,
  DB read/write 0, 실제 네트워크 호출 0. Production 변경 없음.

## DB write 허용 여부
아니오 (읽기 전용)

## push 허용 여부
아니오 — commit·push·deploy·Secrets 변경 전부 사용자 승인 대기.
