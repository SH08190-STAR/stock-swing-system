# PROJECT_STATE — 저장소 현재 상태 스냅샷

> 기준: 2026-07-12, commit a2e9a0e. 값이 바뀌면 이 스냅샷을 갱신한다.

## 상태 스냅샷 기준 커밋 (최신 애플리케이션 기능 커밋)
- a2e9a0e `feat: add dashboard search and fix trade labels` (스냅샷 시점 기준)

## 최신 저장소 커밋 (main HEAD)
- `f40ba07` fix: handle Streamlit auth redirects in smoke check (2026-07-13 push)
- 주의: 이 값은 **운영 정상 확인 커밋(LKG)과 다르다.** f40ba07은 smoke
  스크립트·테스트·문서만 바꿨고 앱 코드는 무변경이므로 운영 앱 동작을
  바꾸지 않는다.

## LAST_KNOWN_GOOD_COMMIT
- `9975719` Revert "feat: refine dashboard spacing" (유지)
- 의미: **운영(Streamlit Cloud)에서 정상 동작이 확인된 커밋.**
  최신 저장소 커밋(현재 f40ba07)과는 별개 개념이며, 두 값은 현재 다르다.
- f40ba07로 LKG를 올리지 않는 이유: 앱 코드 무변경 배포이고, LKG 갱신은
  앱 배포 + smoke check + 10분 안정 확인을 조건으로 하기 때문
  (docs/DEPLOYMENT_GUARDRAILS.md).
- 참고: 위의 a2e9a0e는 "상태 스냅샷 작성 기준 커밋"으로, 운영 정상
  확인 커밋(LKG)과는 별개다.
- 근거: 2026-07-12 streamlit==1.58.0 pin(974494e) 및 기능 커밋 revert 이후
  이 커밋이 배포된 상태에서 운영 정상 (2026-07-13 사용자 확인 기준)
- 갱신 규칙: 배포 후 smoke check + 10분 안정 확인 시에만 갱신

## deploy-smoke 실전 검증 이력
- 2026-07-13: deploy-smoke workflow **최초 실전 검증 성공** (commit f40ba07,
  소요 6분 22초). 303 쿠키 부트스트랩 false negative 수정 후 실제 앱
  health가 리다이렉트 추적으로 최종 200 확인됨.

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
