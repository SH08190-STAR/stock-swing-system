# CURRENT_TASK — 현재 활성 작업

> 이 문서는 **덮어쓰기** 문서다. 새 작업 시작 시 기존 내용을 누적하지 말고
> 아래 템플릿 전체를 새로 채운다. 작업이 없으면 상태를 `대기`로 둔다.

## 상태
완료  <!-- 대기 / 설계 / 구현 / 검수 / push 대기 / 완료 -->

## 완료 기록 (2026-07-13)
- ETF quote-pair v2 병합 `bc2055a` → 부분 hot-reload hotfix 병합 `b0219ab`, main HEAD=`b0219ab`.
- tests·Deploy Smoke workflow 성공 + **운영 앱 실화면 확인 완료**(로그인·매매기록 탭·본주/ETF
  카드·기준일 2026-07-10·환산값 정상, AttributeError·모듈 동기화 실패 없음).
- LAST_KNOWN_GOOD_COMMIT을 `b0219ab`로 갱신(docs/PROJECT_STATE.md).
- DB: prices 58,371, 레버리지 공통일 40/40, trade_records 64·stocks 188·stock_targets 2 불변.
- 사건 기록: docs/incidents/2026-07-13-partial-hot-reload.md.

## FDR end-exclusive 수정 + 본주 07-10 보정 (2026-07-13)
- 문제: FDR/yfinance `end`가 exclusive라 파이프라인이 최신 완료 거래일을 1일 누락.
  ETF 백필은 07-10 포함했으나 워치리스트 US 본주는 07-09에서 멈춤 → 공통일 07-09.
- 코드 수정: app/collector.py에 fdr_end_exclusive/fetch_fdr_through 추가(미국 FDR만
  end+1로 완료일 포함 + 이후 행 제거, KR 무변경). tests/test_fdr_end_boundary.py(8개).
- 데이터 보정: scripts/base_0710_backfill.py로 US 본주 29개에 2026-07-10 행만 insert
  (39-code ETF 백필과 분리된 allowlist/manifest, insert-only). 29행 삽입, canary 2(AAPL·NVDA)+full 27.
- 결과: prices 58,342→58,371(+29), 기존 행 변경 0, 타 테이블 불변, 07-10 외 date write 0,
  allowlist 밖 write 0. **레버리지 40건 최신 공통일 07-10(US 39+KR 1).**
- 롤백: .tmp/quote_pair_base_0710_rollback.sql (삽입 29키만 삭제, 미실행).

## 후속 작업 (2026-07-13) — 레버리지 ETF 가격 수집 (경로 A)
스테이징 검수에서 모든 레버리지 거래가 "동일 기준일 쌍 없음"으로 보류됨.
원인: 레버리지 ETF 가격이 한 번도 수집되지 않음(수집 대상이 정적 워치리스트로
고정, ETF 미포함). quote-pair v2 로직은 정상, 데이터 공급만 비어 있었음.

경로 A(스키마 변경 없음, prices FK 없어 임의 symbol 저장 가능)로 구현:
- app/collector.py: normalize_pipeline_symbol, build_trade_targets (순수 로직)
- app/database.py: get_active_trade_symbols(활성만·완료 제외), code_by_name (read-only)
- scripts/run_daily_update.py: save_trade_symbol_prices 단계 추가 —
  워치리스트 ∪ 활성 trade 본주 ∪ 비어있지 않은 leverage_symbol, 중복/빈값 제거,
  KR 종목명→코드 해소, 본주·ETF 같은 회차·같은 end·같은 공급자로 prices만 upsert,
  개별 실패 격리(요약 collected/skipped/unresolved/failed)
- tests/test_trade_collection.py (신규 15개)
- docs/BACKFILL_PLAN_quote_pairs.md (백필 계획 + dry-run)

dry-run(읽기 전용, DB write 0): 신규 39(KR2/US37), 예상 8,520행,
2025-07-09~2026-07-10, prices만. 미해소 종목명 6(레버리지 아님, 코드 입력 필요).

### 진단 정정 + 옵션 A 백필 실행 (2026-07-13)
- **"ETF 가격 전무"는 오진.** 정밀 재확인 결과 39개 code 전부 prices 이력이 있었고
  2026-06-18 부근에서 갱신 중단(워치리스트 밖이라 일일 수집 누락). 워치리스트 본주는 07-09까지 최신.
- 전 기록 보류 원인은 get_common_close_pair(lookback=10)가 본주(~07-09)·ETF(~06-18)
  창 불일치로 None 반환. lookback 확대로 낡은 쌍 쓰는 임시해결은 금지.
- 기존 데이터 삭제형 롤백은 위험(코드당 200여 행 이력 존재).
- **옵션 A 실행**: 39개 code에 2026-06-19~07-10 누락 키만 insert(upsert 금지).
  549행 삽입(canary 30+full 519), 실패/스킵 0, prices 57,793→58,342, 기존 행 변경 0,
  타 테이블 무변경. **커버리지 40/40**. 롤백 SQL은 삽입 549키만 삭제하도록 준비(미실행).
- 스크립트: scripts/quote_pair_backfill.py (dry-run 기본·--execute 필수·prices 전용·기존 키 skip).
- 미해소 한글 종목명 6(HPSP·LG전자·에코프로·코데즈컴바인·현대로템·현대차)은 ETF 백필
  blocker 아님 — 별도 데이터 정리 항목(본주를 6자리 코드로 수정 필요, 임의 코드 추정 금지).

## (이전) push 대기 기록 — v2 quote-pair 기본 구현

## 목표
revert로 제거된 ETF 환산 가격 일관성 기능을 최소 변경으로 재구현한다
(브랜치 feature/quote-pair-v2, f4babe9는 설계 참고만 — cherry-pick 금지).
UI/UX 구조는 변경하지 않는다.

## 핵심 규칙
- 본주·레버리지 ETF 가격은 동일 공급자(provider) + 동일 기준일(as_of) 쌍만 환산 허용
- 렌더 기본값: Supabase prices의 최신 공통 거래일 종가 쌍.
  공통 거래일 없으면 환산 보류 + "동일 기준일의 가격 쌍을 찾을 수 없습니다"
- 렌더 시 FDR 조회 금지. 외부(FDR) 조회는 레코드별 '최신 가격 조회' 버튼으로
  그 기록의 본주·ETF 한 쌍만, source·as_of 일치 시에만 사용, DB 저장 없음
- 환산 공식·손절·수량(floor(x+0.5))·리스크·완료손익 규칙은 기존 그대로
- 표시: 가격 계산 영역에 출처·기준일·본주가·ETF가 caption

## 구현 내용 (2026-07-13)
- `app/quotes.py` (신규): QuoteSnapshot/QuotePair(frozen dataclass),
  make_pair(일관성 판정), latest_common_close(공통 거래일 선택),
  fetch_fdr_snapshot/fetch_fdr_pair(외부 조회, 순수 로직 — Streamlit 무의존)
- `app/database.py`: get_latest_quote(가격+기준일), get_common_close_pair
  (read-only select만 — DB write 없음)
- `dashboard/app.py`: _resolve_symbol, db_quote_pair/db_single_quote
  (ttl=600, max_entries=64), fdr_quote_pair/fdr_single_quote
  (ttl=300, max_entries=32, 쌍 단위 — DataFrame 캐시 없음),
  clear_price_caches, 레코드별 외부 조회(_fetch_external_quote, 세션 보관),
  _trade_calc를 QuotePair 기반으로 재작성(불일치 시 환산 None 보류),
  카드/상세에 근거 caption + 보류 안내 + '최신 가격 조회' 버튼
- `tests/test_quotes.py` (신규 23개): 쌍 일관성 성공/날짜 불일치/출처 불일치,
  공통 거래일 선택/없음/무효 close 제외, FDR 쌍 성공/한쪽 실패/asof 불일치,
  db 함수 mock 검증, database 함수 존재·import 검증, _trade_calc ETF 환산·
  본주 단독·보류·일반 반올림, 완료손익 규칙 보존

## 수정 허용 파일
- dashboard/app.py, app/database.py, app/quotes.py(신규),
  tests/test_quotes.py(신규), docs/CURRENT_TASK.md

## 수정 금지
- UI/UX 구조·탭 구조·CSS, CSV, schema.sql, requirements.txt,
  GitHub workflow, DB 데이터(stock_targets, trade_records)

## DB write 허용 여부
아니오 (신규 DB 함수는 전부 read-only select)

## push 허용 여부
아니오 (스테이징 검증 후 사용자 승인 대기)

## 검증
- [x] py_compile (app/quotes.py, app/database.py, dashboard/app.py, tests)
- [x] tests/test_quotes.py 23 passed
- [x] 전체 pytest 141 passed (.tmp/pytest.log)
- [x] git diff --check 통과
- [x] predeploy_check — 기능 검사 전부 PASS (health 200 + 120초 생존 포함,
      git clean 항목만 커밋 전 실행이라 FAIL — 커밋 0f53b24 후 해소)
- [x] 매매기록 화면 실검수 (로컬 Streamlit 완전 재시작, 2026-07-13):
      KR 본주 카드 Supabase 출처·기준일 표시, 미조회 종목 보류 안내,
      US 레버리지 쌍 없음 → 환산 보류 메시지, 버튼 클릭 시 FDR 한 쌍
      조회(SNDK/SNXX 동일 기준일 2026-07-10, 환산·수량 검산 일치),
      새 세션에서 DB 기준 복귀(외부 결과 비저장) 확인, DB write 없음
