# PROJECT_STATE — 저장소 현재 상태 스냅샷

> 기준: 2026-07-12, commit a2e9a0e. 값이 바뀌면 이 스냅샷을 갱신한다.

## 상태 스냅샷 기준 커밋 (최신 애플리케이션 기능 커밋)
- a2e9a0e `feat: add dashboard search and fix trade labels` (스냅샷 시점 기준)

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
