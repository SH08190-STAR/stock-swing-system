# PROJECT_STATE — 저장소 현재 상태 스냅샷

> 기준: 2026-07-14, commit 43088fa. 값이 바뀌면 이 스냅샷을 갱신한다.

## 상태 스냅샷 기준 커밋 (최신 애플리케이션 기능 커밋)
- a2e9a0e `feat: add dashboard search and fix trade labels` (스냅샷 시점 기준)

## 최신 저장소 커밋 (main HEAD)
- `43088fa` merge: reorganize dashboard navigation (2026-07-14 push)
- UI/UX 1단계(상위 내비게이션 4개 메뉴 재편, dashboard/app.py만 변경) 배포이며
  운영 검증까지 완료돼 아래 LKG와 동일하다.

## LAST_KNOWN_GOOD_COMMIT
- `43088fa` merge: reorganize dashboard navigation (2026-07-14 갱신)
- 의미: **운영(Streamlit Cloud)에서 정상 동작이 확인된 커밋.** 현재 main HEAD와 동일.
- 근거: UI/UX 1단계 — st.tabs 9개를 key 지정 horizontal radio 상위 메뉴 4개(홈·섹터·매매·더보기)로
  재편(기능·계산·quote-pair·CSS 무변경, dashboard/app.py 단일 변경). 2026-07-14 tests·Deploy Smoke
  workflow 성공 + 운영 앱 실화면 확인(로그인·4개 메뉴 전환·기존 9개 기능·공통 metric/검색/사이드바 유지·
  매매 rerun 후 메뉴 유지·본주/ETF 카드·기준일 07-10·환산값 정상·AttributeError·모듈 동기화 실패 없음).
- 이전 LKG `b0219ab`에서 갱신: 위 조건(앱 배포 + smoke 통과 + 운영 실화면 확인) 충족.
- 참고: `a2e9a0e`는 "상태 스냅샷 작성 기준 커밋"으로 LKG와 별개다.
- 갱신 규칙: 배포 후 smoke check + 안정 확인 + 운영 실화면 확인 시에만 갱신

## deploy-smoke 실전 검증 이력
- 2026-07-13: deploy-smoke workflow **최초 실전 검증 성공** (commit f40ba07,
  소요 6분 22초). 303 쿠키 부트스트랩 false negative 수정 후 실제 앱
  health가 리다이렉트 추적으로 최종 200 확인됨.
- 2026-07-14: deploy-smoke #7 성공 (commit 43088fa, 소요 6분 29초). tests #30도 성공.

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
- 미push 로컬 변경: 없음 (이번 운영 문서·Skills 작업분 제외)
