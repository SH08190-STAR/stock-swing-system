# CURRENT_TASK — 현재 활성 작업

> 이 문서는 **덮어쓰기** 문서다. 새 작업 시작 시 기존 내용을 누적하지 말고
> 아래 템플릿 전체를 새로 채운다. 작업이 없으면 상태를 `대기`로 둔다.

## 상태
검수  <!-- 대기 / 설계 / 구현 / 검수 / push 대기 / 완료 -->

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
- [ ] predeploy_check (health 200 + 120초 생존) — 진행 중
- [ ] 매매기록 화면 실검수 (로컬 Streamlit 완전 재시작)
