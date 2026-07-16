# PROJECT_STATE — 저장소 현재 상태 스냅샷

> 기준: 2026-07-17, main=4787186. 값이 바뀌면 이 스냅샷을 갱신한다.

## 상태 스냅샷 기준 커밋 (최신 애플리케이션 기능 커밋)
- a2e9a0e `feat: add dashboard search and fix trade labels` (스냅샷 시점 기준)

## 최신 저장소 커밋 (main HEAD)
- `4787186` fix: restrict Toss relay overlay to US trades (2026-07-17 운영 배포)
- main = staging/ui-v3 = `4787186` (fast-forward, merge commit 없음).
- 토스 시세 Relay 연동 전체가 운영 반영된 상태 — 아래 "토스 Relay 운영" 참조.

## LAST_KNOWN_GOOD_COMMIT
- `4787186` fix: restrict Toss relay overlay to US trades (**2026-07-17 갱신**)
- 의미: **운영(Streamlit Cloud)에서 정상 동작이 확인된 커밋.** 현재 main HEAD와 동일.
- 근거: main FF 후 GitHub checks 6건 전부 success(pytest·relay-tests·
  docker-build-health·smoke), Production 4분 smoke PASS(검사 16회·실패 0·303→200),
  **운영 실화면 사용자 확인(2026-07-17)** — 국장 우회 정상, 미장 TP IN·진입 provider
  Toss, 상태 탭 왕복·최신 가격 조회 정상, Relay POST 4건 전부 200, 오류 status 0,
  AttributeError·traceback·segfault 0. 전체 pytest 363 passed.
- 이전 LKG `39b8c95`(UI/UX 3D)에서 갱신: 갱신 조건(배포 + smoke 통과 +
  운영 실화면 확인) 충족. `39b8c95`는 **historical rollback reference로 유지**.
- 참고: `a2e9a0e`는 "상태 스냅샷 작성 기준 커밋"으로 LKG와 별개다.
- 갱신 규칙: 배포 후 smoke check + 안정 확인 + 운영 실화면 확인 시에만 갱신

## 릴리스 tag (rollback 기준)
- `prod-toss-relay-live-20260717` → **`4787186`** — 현재 운영 릴리스(Toss Relay live).
- `prod-pre-toss-relay-20260716` → **`3997bb6`** — Toss Relay 도입 직전 main(rollback 기준).
- `39b8c95` — historical operational LKG(UI/UX 3D 시점).
- tag는 수정·삭제하지 않는다. rollback 시 위 tag를 기준으로 판단한다.

## UI/UX 진행 상태
- 3A(전역 config.toml 라이트 테마): **폐기** — 스테이징 Segmentation fault 재현.
  .streamlit/config.toml 사용 금지 유지.
- 3B(색상 토큰·뱃지 팔레트 통일): **운영 검증 완료** (`9bbd36d`, 2026-07-15).
- 3C(앱 헤더·요약 밴드·내비게이션 정돈): **운영 검증 완료** (`67ec9c9`, 2026-07-15).
- 3D(카드 정보 위계·경고·손익 표현): **운영 검증 완료** (`39b8c95`, 2026-07-15).
- **UI/UX 3단계(3B~3D) 전체 완료.** 3A(전역 config.toml)만 폐기 유지.

## 토스 Relay 운영 — **완료 (2026-07-17 운영 배포·검증 완료)**

### 최종 아키텍처
```
Streamlit Cloud ──HTTPS──▶ Fly.io Relay (nrt, static egress IPv4 1개)
  (TOSS_RELAY_URL/TOKEN)         └──▶ Toss Open API (허용 IP = 그 egress IPv4 1개)
```
- 배경: Streamlit Cloud outbound IP가 토스 허용 한도(10개)를 초과해 **직접 호출
  구조는 폐기**. 고정 egress IP를 가진 Relay 1대를 경유한다.
- Relay: `services/toss_relay/`(FastAPI) — Fly app nrt / shared-cpu-1x 256MB /
  **Machine 최대 1대** / uvicorn worker 1 / app-scoped static egress IPv4 1쌍.
  공개 endpoint는 `GET /healthz`·`POST /v1/prices` **2개뿐**(주문·계좌·잔고 없음).
  실제 앱 이름·URL·egress IPv4는 tracked 파일에 기록하지 않는다(로컬
  `services/toss_relay/fly.toml`(.gitignore)·Fly 대시보드 참조).

### 보안 경계
- **Streamlit**: `TOSS_RELAY_URL`, `TOSS_RELAY_TOKEN` **두 개만**. Toss OAuth를
  직접 다루지 않으며 access token을 보지 않는다.
- **Fly Relay**: `TOSS_CLIENT_ID`, `TOSS_CLIENT_SECRET`, `RELAY_SHARED_SECRET`.
  **Toss credentials는 Relay에만 존재** — Streamlit에 절대 넣지 않는다.
- Relay 인증: `Authorization: Bearer`(hmac.compare_digest, 최소 32자). 오류 응답은
  code + 고정 문구만(원본 body·token 비노출). CORS 없음, docs/openapi 비활성.

### 시장 정책 (US-only)
- **US 화면만 Relay 활성** — `dashboard/app.py`의 market gate가 canonical `"US"`가
  아니면(KR·미지정·미지 값 포함, fail-closed) `toss_enabled()` 검사 전에 우회한다.
- **KR(국장)은 기존 Supabase/FDR 경로 유지** — Relay 호출 0회, 실패 안내 0회.
- 이유: KR 심볼(숫자 코드 + 한글 종목명)의 Toss 지원 형식이 **미검증**(실호출 502).
  KR 활성화는 **별도 검증 없이는 금지**.

### 부분 반환 정책 (`app/toss.py`)
- 200 응답의 **개별 item 불량**(null/0/음수/비숫자 가격·timestamp 누락/파싱불가/
  naive·symbol 누락·비dict)은 **그 item만 skip**하고 정상 item은 반환.
  누락 심볼은 결과에 넣지 않아 호출측이 pair 단위 DB fallback을 한다(placeholder 금지).
- 빈 result 목록 → 정상 빈 결과. **항목이 있는데 전부 불량 → TossResponseError**
  (Relay 502 `TOSS_BAD_RESPONSE`) — 전체 손상을 숨기지 않는다.
- HTTP/upstream 오류(401/403/404/429/5xx/timeout) 매핑은 무변경. 자동 retry·
  bisect·negative cache·심볼 whitelist·특정 티커 예외 처리 **없음**.

### 가격 우선순위·캐시
- 우선순위(`_trade_calc` 한곳): 수동 외부조회(`_ext_quote`) → **Relay Toss** →
  Supabase DB(공통일자 pair/최신 quote) → FDR(수동 버튼).
- 레버리지 쌍은 본주·ETF **둘 다 Toss + 기준시각 차이 ≤300초**일 때만 성립.
  한쪽 누락·skew 초과·오류 시 **쌍 전체 DB fallback**(출처 혼합 금지).
- Relay client는 `st.cache_resource`(프로세스 1개), 가격 batch는
  `st.cache_data(ttl=20)`(심볼 튜플 키 — token은 인자·key·session_state에 없음).
  새로고침은 batch 캐시만 clear(client·token 유지, Toss OAuth는 Relay 내부 소관).

### 운영 검증 결과 (2026-07-17)
- Production: Relay POST **4건 전부 HTTP 200**, 오류 status(401/429/502/503/504) **0**,
  `TOSS_AUTH_FAILED`·`TOSS_IP_FORBIDDEN` **0**, AttributeError·traceback·segfault **0**,
  secret/token 로그 노출 **0**. 국장 대응 POST **0회**(gate 정상), 미장 TP IN·진입
  provider **Toss**, 상태 탭 왕복·최신 가격 조회 정상. 4분 smoke 16회·실패 0.
- 20초 TTL 캐시가 동일 batch 반복을 정상 억제(탭 8~12회 전환 대비 POST 4건).
- Fly Relay version 4 / Machine 1대 / nrt / started / health passing / restart 0.
- DB write 없음(Relay는 DB 미연결, 대시보드는 읽기 전용 경로만 사용).

### 미해결 항목
- **KR Toss 지원**: 별도 검증 필요(현재 의도적 비활성). 숫자 코드·한글 종목명이
  섞여 나가는 문제와 Toss의 KR 심볼 포맷 확인이 선행돼야 한다.
- **과거 native segfault 근본 원인 미확정**: 0161184 staging 사건은 fix 1(e25046e)의
  비활성 우회로 격리했을 뿐 원인 라인은 미확정. 현재 재현 없음.
- **비용**: Relay 월 약 **$5.6**(Machine ~$2 + static egress IPv4 $3.60 + 데이터 ~$0).
- 운영 정책: static egress IP **release 금지**, Machine **최대 1대**(토스는 클라이언트당
  활성 토큰 1개 — 2대면 토큰 상호 무효화), 주문·계좌 endpoint 추가는 별도 승인 필요.

## 이력 — 토스증권 Open API 연동 경과
- 목표: Toss Open API로 본주·레버리지 ETF 현재가를 화면 표시용 overlay로 반영
  (Supabase 최신 종가는 fallback·과거 데이터로 유지, DB 틱 저장 없음).
- **1차 foundation 완료**(main=3997bb6): `app/toss.py`(토큰 관리 + `/api/v1/prices`
  batch 조회 순수 모듈) + `tests/test_toss.py`(mock 25건). GitHub Tests success.
- **2차 live overlay(0161184) — staging segfault 사건으로 수정 중**:
  0161184를 staging/ui-v3에 배포 후 사용자 재현(로그인→매매→미장→TP IN)에서
  Segmentation fault(traceback 없음, credentials 미설정·Toss 호출 0회 상태).
  revert(59144b1) 후 동일 동작 정상 → **overlay commit과 crash 상관성 확인,
  원인 라인 미확정**. 0161184 전체 재배포·main 병합 금지.
  사건 로그: .tmp/incident_2026-07-15_1.log. staging/ui-v3=59144b1(revert).
- **fix 1 — 비활성 스테이징 검증 성공**: feature/toss-live-overlay-fix1=`e25046e`
  (기준 59144b1 + cherry-pick 0161184 + 비활성 경로 완전 우회). staging/ui-v3에
  e25046e 배포 후 credentials 미설정 상태 검증 성공 — segfault 재현 없음.
  전체 pytest 248 passed 기준 유지. main 병합은 미실행.
- **직접 Toss 호출 방식 폐기(2026-07-15)**: Streamlit Community Cloud outbound
  IP 수가 토스 허용 IP 한도(10개) 초과 → 운영에서 직접 호출 구조 사용 불가.
  일부 IP만 등록하는 방식 금지. **Fly.io static-egress Relay 방식 채택**
  (Tokyo nrt, shared-cpu-1x 256MB 1대 상시 실행, app-scoped static egress
  IPv4 1개만 토스에 등록, Fly HTTPS endpoint 사용·별도 도메인 없음).
- **Relay 배포·실조회 검증 완료(2026-07-16)**: feature/toss-relay-service=31062a8
  push, GitHub tests·relay-tests·docker-build-health 전부 success. Fly Relay 앱
  (nrt, shared-cpu-1x 256MB, Machine 1대, worker 1 — 실제 앱 이름·URL·egress
  IPv4는 tracked 파일에 기록하지 않는다: 로컬 fly.toml·Fly 대시보드 참조) 배포,
  app-scoped static egress IPv4 1쌍(nrt)을 Toss 허용 IP에 등록.
  credentials 재입력 사건 2회(1글자 잘림 → OAuth 401 invalid_client) 후 정상화 —
  NVDA/NVDL 실조회 200 OK(Decimal 문자열·USD·timezone-aware timestamp),
  secret/token 로그 비노출, restart 0. 운영 비용 약 $5.6/월(Machine ~$2 +
  egress IP $3.60). 실제 services/toss_relay/fly.toml은 로컬 전용(.gitignore) —
  dockerfile 경로는 fly.toml 위치 기준 "Dockerfile"이 검증값(example에 반영).
- **Streamlit 연동 완료**(`007a7d8`): 직접 Toss 호출 경로 제거 —
  app/toss_relay_client.py(순수 클라이언트) + config TOSS_RELAY_URL/TOSS_RELAY_TOKEN
  + dashboard `_toss_client` 교체. Fix 1 비활성 우회 계약 유지.
- **부분 반환 견고화**(`9d60937`): 일시 데이터 지연 종목 1개가 batch 전체를 502로
  만들던 all-or-nothing 파싱을 per-item skip으로 교체. Fly Relay version 4로 배포.
- **US-only gate**(`4787186`): KR batch(숫자 코드 + 한글 종목명)가 Relay로 나가
  502 + 실패 안내가 뜨던 문제를 market gate로 차단. Streamlit 전용 변경.
- **운영 배포 완료**(2026-07-17): main FF `3997bb6`→`4787186`, LKG 갱신.
  현재 정책·검증 결과는 위 "토스 Relay 운영" 섹션 참조.

## deploy-smoke 실전 검증 이력
- 2026-07-13: deploy-smoke workflow **최초 실전 검증 성공** (commit f40ba07,
  소요 6분 22초). 303 쿠키 부트스트랩 false negative 수정 후 실제 앱
  health가 리다이렉트 추적으로 최종 200 확인됨.
- 2026-07-14: deploy-smoke #7 성공 (commit 43088fa, 소요 6분 29초). tests #30도 성공.
- 2026-07-14: 커밋 86333df tests·Deploy Smoke Check 모두 success (main check-runs 확인).
  병합 전 스테이징(feature 6aab986) 3분 Cloud smoke PASS(검사 12회·연속 실패 0·303→200).
- 2026-07-14: 커밋 cd7f16c tests·Deploy Smoke Check 모두 success (smoke 371초). 병합 전
  독립 fresh 스테이징 2종(main control, basis-fix control-2 = 1e72627) 각 10분 Cloud smoke PASS
  (검사 29회·연속 실패 0). 운영 앱 Reboot 후 10분 smoke PASS(검사 29회·연속 실패 0, 19:30~19:41 KST).

## USD basis caption 표시 버그 수정 및 Streamlit Cloud 장애 대응 (2026-07-14)
> 분류: UI/UX 단계 작업이 아니다(별도 버그 수정 + 운영 장애 대응). UI/UX 3단계(색상·간격·시각
> 디자인 개선)는 미착수로 유지한다.

- `cd7f16c` merge: fix USD basis caption rendering. fix/us-basis-caption-dollar-rendering(`1e72627`)를
  --no-ff 병합. **변경 파일 3개**: dashboard/app.py(+7/-2: `_basis_caption` docstring + `$`→`\$`
  escape 1줄), tests/test_trades.py(+36: basis escape 회귀 4건), docs/CURRENT_TASK.md.
- 원인: `_basis_caption`이 USD 레버리지에서 "본주 $1,915.92 · ETF $28.06"처럼 `$` 2개 포함 문자열을
  반환 → st.caption(Markdown)이 `$...$` 구간을 LaTeX 수식(KaTeX)으로 렌더(초록 이탤릭). 국장(원화)은
  `$` 없음, 미장 본주 단독은 `$` 1개라 미발생.
- 수정: 반환 직전 `.replace("$","\\$")` 1줄. 숫자 포맷·계산·저장값·모바일 CSS·내비게이션·DB 무변경.
- **운영 검증 완료(2026-07-14, 사용자 확인)**: 미장 레버리지/본주 basis 달러 일반 텍스트(KaTeX 0·
  백슬래시/초록 수식 없음)·상세 expander·국장 원화 카드·모바일 압축 정상. tests·Deploy Smoke Check
  success. 운영 앱 Reboot 후 10분 smoke PASS.
- DB: prices 58,371(레버리지 40/40 실조회)·trade_records 64·stocks 188·stock_targets 2 불변. DB write 없음.

## 스테이징 배포 인스턴스 Segmentation fault 사건·복구 (2026-07-14)
- 증상: basis-fix 병합 전 스테이징(`stock-swing-basis-fix-stagin`)에서 최초 실행 + 허용된 Reboot 1회
  모두 Segmentation fault(최초 PID 189, Reboot 후 PID 182). Python traceback 없음, Supabase secret
  오류 없음. (초기 브라우저 "Failed to fetch dynamically imported module"는 빌드/재기동 중 프론트
  청크 fetch 실패로 별개 현상, 이후 "Oh no. Error running app.")
- A/B 진단(읽기 전용): 동일 commit/tree(`1e72627`, tree `3f0d1a9`)를 별도 배포 좌표에 fresh 배포한
  두 독립 앱(main control `kqf4sy24…`, basis-fix control-2)은 모두 정상 — 10분 smoke PASS(각 검사
  29회·연속 실패 0), segfault·traceback·프로세스 재시작 없음. 설치 버전도 정상 조합(Python 3.12.13·
  streamlit 1.58.0·numpy 2.5.1·pyarrow 25.0.0)에서 무결.
  → fresh Cloud build/floating dependency "자체"는 원인 아님(systemic 기각). 코드(escape 1줄)는
  런타임에 inert → segfault 유발 불가.
- 운영 앱: 최초 hot update(main HEAD 갱신) 후 PID 221 segfault → 전체 Reboot 1회 후 fresh process
  정상 기동(새 프로세스 2026-07-14 10:24 UTC, Uvicorn 정상), 10분 smoke PASS(검사 29회·연속 실패 0,
  19:30~19:41 KST), 최신 Cloud 로그 segfault·traceback·재시작 없음.
- working cause(확정 아님, 추정): **장시간 실행 프로세스가 GitHub hot update 후 불안정해져
  Segmentation fault 발생**. fresh process에서는 재현되지 않음. 근본 원인 완전 확정은 아님.
  (use_container_width deprecation 경고는 이번 장애 원인이 아니며 무관한 정보성 로그다.)
- 폐기 후보: `stock-swing-basis-fix-stagin`(장애 인스턴스). 진단 종료 후 삭제 대상으로만 기록
  (이번 작업에서는 삭제·Reboot하지 않음).

## UI/UX 2단계 (모바일 카드 밀도 개선) 운영 검증 (2026-07-14)
- `86333df` merge: compact dashboard cards on mobile. feature/mobile-card-density-v2(`6aab986`)를
  --no-ff 병합. **dashboard/app.py + docs/CURRENT_TASK.md 변경**(app.py +55/-2: CSS 상수·
  컨테이너 key 2곳·main() 주입 1줄).
- 내용: 섹터/매매 카드 컨테이너에 key(`stock_card_*`/`trade_card_*`) 부여 → Streamlit 1.58.0이
  `st-key-*` 클래스 생성. 그 범위로 한정한 `@media (max-width:640px)` 전용 `_MOBILE_CARD_CSS` 1회
  주입(카드 padding 15px→0.6/0.75rem·세로 gap 16px→0.4rem·metric value 36px→1.35rem·label
  14px→0.75rem·caption line-height→1.3·카드 내 expander summary padding 축소). :has·nth-child·
  전역 stMetric 선택자 미사용.
- 무변경 확인: 계산 로직·ETF quote-pair·FDR·DB·캐시·로그인 gate·모듈 reload guard·4개 내비게이션·
  기존 함수명/시그니처/위젯 key·색상/뱃지/로고/그림자, requirements/schema/CSV/workflow.
  상단 요약 metric 5개·사이드바·검색·신규 기록 폼은 카드 key 밖이라 CSS 미적용.
- 카드 높이(모바일 390px, 접힘): 섹터 285→207px(-27%), 매매 본주 885→624px(-30%),
  매매 레버리지 822→587px(-29%). 데스크톱 1440px 카드 외형 무변경(px 단위 일치).
- **운영 검증 완료(2026-07-14, 사용자 확인)**: 모바일 섹터/본주/레버리지 카드 압축·상세 expander·
  가격/기준일/출처/환산값/수량 누락 없음·상단 metric/사이드바/검색/신규 기록 폼 정상·가로
  스크롤/겹침/잘림 없음·데스크톱 레이아웃 정상, 빨간 오류·AttributeError·모듈 동기화 실패 없음.
  tests·Deploy Smoke Check 모두 성공.
- DB: prices 58,371(레버리지 40건 공통일 40/40 실조회 재검증), trade_records 64·stocks 188·
  stock_targets 2 불변. DB write 없음.

## UI/UX 1단계 (상위 내비게이션 재편) 운영 검증 (2026-07-14)
- `43088fa` merge: reorganize dashboard navigation. feature/ui-navigation-v2(`62724be`)를
  --no-ff 병합. **dashboard/app.py 단일 변경**(main() 라우팅 영역, +100/-92).
- 내용: st.tabs 9개 → key 지정 horizontal st.radio 상위 메뉴 4개(홈·섹터·매매·더보기) +
  하위 radio(섹터·더보기). 기존 9개 화면을 로직·문구·위젯 key·CSV 위치 변경 없이 재배치.
  top_nav를 radio로 유지해 매매 rerun 후에도 메뉴 유지.
- 무변경 확인: 계산 로직·ETF quote-pair·FDR·DB·캐시·로그인 gate·모듈 reload guard·
  CSS/카드 디자인/색상/간격, requirements/schema/CSV/workflow.
- **운영 검증 완료(2026-07-14, 사용자 확인)**: 로그인·4개 메뉴 전환·기존 9개 기능 접근·
  공통 metric/검색/사이드바 유지·매매 가격 새로고침 후 메뉴 유지·본주/ETF 카드·기준일 2026-07-10·
  환산값 정상, 빨간 오류·AttributeError·모듈 동기화 실패 없음. tests·Deploy Smoke 모두 성공.
- DB: prices 58,371(레버리지 40건 공통일 40/40 실조회 재검증), trade_records 64·stocks 188·
  stock_targets 2 불변. DB write 없음.

## ETF quote-pair + hotfix 운영 검증 (2026-07-13)
- `bc2055a` merge: ETF quote-pair v2 (본주·ETF 동일 provider/as_of 쌍, 일일 파이프라인
  수집 확장, FDR end-exclusive 수정, 본주 07-10 보정 549+29행). tests·deploy-smoke 성공.
- 배포 후 부분 hot-reload로 매매 탭 AttributeError 발생 → `b0219ab` hotfix: 런타임 모듈
  정합성 가드(계약 검사 + 1회 reload 자동 복구 + 예외 격리).
- **운영 검증 완료(2026-07-13, 사용자 확인)**: 로그인·매매기록 탭·본주/ETF 카드·기준일 2026-07-10·
  환산값 정상, AttributeError·모듈 동기화 실패 없음. tests·Deploy Smoke 모두 성공.
- DB: prices 58,371(레버리지 40건 공통일 40/40), trade_records 64·stocks 188·stock_targets 2 불변.

## 기술 구조
- Python 3.12 / Streamlit 대시보드 / Supabase(PostgreSQL)
- 배포 흐름: GitHub main → Streamlit Cloud 자동 배포
- 일일 데이터: GitHub Actions `daily-update.yml` → `scripts/run_daily_update.py`
  (거래일 판정 후 수집·분류, FORCE_RUN=1로 수동 강제 실행 가능)

## 주요 디렉터리와 핵심 파일
- `app/` — 핵심 로직: collector.py(가격 수집), classifier.py(단기스윙 분류),
  database.py(Supabase 접근), watchlist.py, notifier.py(텔레그램), config.py
- `dashboard/app.py` — Streamlit 대시보드 (섹터 카드, 매매기록, 검색)
- `scripts/` — run_daily_update.py, initialize_db.py, schema.sql
- `tests/` — 8개 테스트 파일
- `watchlist.csv` — 유니버스 정의 (루트)
- 배경 문서: PROJECT_SPEC.md, ARCHITECTURE.md, DATA_MODEL.md, README_HANDOFF.md

## DB 테이블 (scripts/schema.sql)
stocks, prices, history, errors, meta, stock_targets, trade_records

## 현재 수치 (snapshot @ a2e9a0e)
- 유니버스: 188종목 (watchlist.csv)
- 테스트: 88개 collected, 전체 passed

## 완료된 핵심 기능
- 일평균 거래대금 기준 단기스윙 자동 분류 + 12개월 가격 수집
- 52주 고점 지표 (장중 High 기준, 결측 시 close fallback)
- 섹터 카드 ↔ 매매기록(waiting/entered/tp_in) 연동
- 대시보드 검색, 모바일 카드, 매매 가격 표시 개선
- 텔레그램 알림

## 알려진 문제 / 미push 변경
- 거래대금 소스: pykrx/FDR이 거래대금 미제공 → data.go.kr 공공 API 전환 진행 중
  (API 키 발급 대기)
- 미장 basis caption `$...$` 수식 렌더링 버그: **해결됨(`cd7f16c`, 2026-07-14)** — `_basis_caption`
  반환에 `$`→`\$` escape 적용. 위 "USD basis caption 버그 수정 운영 검증" 참조.
- (참고) 스테이징 인스턴스 Segmentation fault 사건: working cause "장시간 실행 프로세스가 hot update
  후 불안정 → segfault"(추정). fresh process·Reboot로 복구. 위 사건·복구 섹션 참조. 근본 원인 미확정.
- staging segfault 사건(2026-07-15): 0161184 배포 상태에서 매매→미장→TP IN 재현,
  revert 59144b1로 격리 후 정상. 원인 라인 미확정 — fix 1(e25046e)로 비활성 경로
  우회, 스테이징 검증 성공.
- 토스 Relay 연동: **운영 배포·검증 완료**(main=LKG=`4787186`, 2026-07-17).
  경과의 두 사건은 모두 해결됨 — ①staging 활성 직후 502 3건: 일시 데이터 지연
  종목의 불량 item 1개가 all-or-nothing 파싱으로 batch 전체를 실패시킨 것
  → `9d60937` per-item skip으로 해결(Fly Relay version 4 배포). ②국장 진입 502 +
  안내: KR batch가 market 필터 없이 Relay로 전송된 것 → `4787186` US-only gate로
  차단. 현재 정책·검증 결과는 "토스 Relay 운영" 섹션 참조.
- **KR Toss 지원은 의도적 비활성** — 숫자 코드·한글 종목명 혼재와 Toss의 KR 심볼
  포맷이 미검증. 별도 검증 단계 없이 활성화 금지.
- 미push 로컬 변경: 없음 (main·staging 모두 `4787186`, 작업 트리 clean).
