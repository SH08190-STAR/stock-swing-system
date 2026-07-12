# BACKFILL PLAN — 레버리지 ETF 가격 백필 (quote-pair v2)

> 목적: 활성 trade_records의 본주·레버리지 ETF 가격을 `prices`에 채워
> 레버리지 거래가 DB 동일 기준일 쌍으로 자동 환산되게 한다.

## ⚠️ 초기 진단 정정 (2026-07-13)

- **"ETF 가격 전무" 진단은 잘못이었다.** 첫 진단 스크립트가 ETF prices를 "없음"으로
  표시했으나, 정밀 재확인(count exact·행조회·min/max, 존재하지 않는 code로 필터 검증)
  결과 **39개 code 전부 prices 이력이 있었고, 2026-06-18 부근에서 갱신이 중단된 상태**였다
  (워치리스트에 없어 일일 수집에서 빠졌기 때문). 워치리스트 본주는 최신(2026-07-09).
- 전 기록 보류의 실제 원인: `get_common_close_pair(lookback=10)`가 본주 최근10일(~07-09)과
  ETF 최근10일(~06-18) 창이 겹치지 않아 None을 반환. 데이터는 06-18에 공통일이 있었으나
  좁은 lookback이 못 봄. (lookback을 넓혀 낡은 06-18 쌍을 쓰는 임시 해결은 **금지** — 신선한
  최신 공통일을 만들어야 함.)
- **기존 데이터 삭제형 롤백은 위험**: 39개 code에는 백필 이전부터 200여 행의 이력이 있어,
  "code 통째 삭제" 롤백은 기존 이력을 파괴한다. → 아래 옵션 A는 **삽입한 키만** 삭제한다.

## 실제 실행: 옵션 A (누락 최근 날짜만 insert) — 2026-07-13 완료

- 대상: 확정 39개 code allowlist. 날짜 2026-06-19 ~ 최신 완료 거래일(2026-07-10).
- 방식: 기존 (code,date) 키는 건드리지 않고, **없는 키만 plain insert**(upsert/overwrite 금지).
- 결과: **549행 삽입**(canary 30 + full 519), 실패 0, 스킵 0. prices 57,793 → 58,342.
  기존 행 변경 0, allowlist 밖 write 0, prices 외 테이블 무변경(trade_records 64/stocks 188/stock_targets 2).
- 커버리지: **활성 레버리지 40건 전부 DB 공통 거래일 쌍 확보(40/40).**
- 롤백: `.tmp/quote_pair_backfill_rollback.sql`에 **삽입한 549키만 삭제**하는 SQL 준비(미실행).
- 실행 스크립트: `scripts/quote_pair_backfill.py` (allowlist·dry-run 기본·--execute 필수·manifest 필수·prices 전용·기존 키 skip).

---
### (참고) 최초 계획 — 아래는 정정 전 초안이며 실행하지 않았다.
> **이 문서는 실행 계획이다. 실제 DB write는 사용자 승인 후에만 실행한다.**

## dry-run 결과 (2026-07-13, 읽기 전용 — DB write 0건)

기준 거래일 `end = 2026-07-10` (최근 KR 거래일). 파이프라인과 동일한
대상 산출·해소 로직으로 계산.

| 항목 | 값 |
|---|---|
| 활성 매매 심볼(중복 제거) | 91 |
| 워치리스트로 이미 수집(스킵) | 46 |
| 미해소 종목명(조회 불가) | 6 |
| **신규 수집 대상** | **39** (KR 2, US 37) |
| fetch 성공 | 39 / 39 (실패 0) |
| **예상 신규 prices 행수(upsert)** | **약 8,520행** |
| 대상 날짜 범위 | 2025-07-09 ~ 2026-07-10 (약 12개월, FETCH_MONTHS) |
| upsert 대상 테이블 | `prices` (on_conflict=code,date) |

### 신규 수집 대상 (39)
- US 37: 레버리지 ETF 34개 전량(NVDL·TSLL·AAPU·SNXX 등) + 워치리스트 밖 본주(IREN·MSTR·NFLX·RGTI)
- KR 2: 국내 레버리지 ETF 코드(예: 0193W0) + 워치리스트 밖 KR 코드

### 미해소 종목명 6 (별도 보고 — 이번 백필 대상 아님)
`HPSP, LG전자, 에코프로, 코데즈컴바인, 현대로템, 현대차`
- 원인: trade_records.symbol에 **코드가 아닌 종목명**으로 입력됨 + stocks/워치리스트에도 없음
  → FDR 티커 조회 불가(404). **레버리지 거래 아님(본주 단독)**, 이번 목표(레버리지 자동환산)와 무관.
- 조치(사용자): 해당 기록의 본주를 6자리 코드로 수정하면 다음 회차에 자동 수집됨. 데이터 수정이므로 승인 전 변경 금지.

## upsert 대상 / 영향 범위
- **쓰는 테이블: `prices`만** (신규 code의 신규 (code,date) 행 삽입).
- 39개 신규 code는 현재 `prices`에 전무 → 전부 순수 추가(기존 행 갱신 없음).
- 미변경: stocks, trade_records, stock_targets, schema. classification 저장 안 함(워치리스트 탭 노출 없음).

## 실행 명령 (승인 후)
파이프라인의 심볼 수집 단계만 단독 호출 — prices 외 write 없음:

```bash
py -3.12 -c "import datetime as dt; import scripts.run_daily_update as up; \
from app import collector; end = collector.latest_trading_day() or dt.date.today(); \
print(up.save_trade_symbol_prices(end, up.now_kst_str(), ''))"
```

- `.env`에 설정된 Supabase에 write한다. 스테이징(동일 Supabase를 보는 앱)에서 먼저 확인 후 운영 판단.
- 재실행 안전: `save_ohlcv`는 on_conflict=code,date upsert → 같은 날짜 재실행에도 중복 행 없음.

## 검증 (실행 후)
```bash
# 커버리지 재확인(읽기 전용): 레버리지 40건 중 DB 공통일 쌍 OK 수 확인
py -3.12 scratchpad/diag_quotes.py    # 또는 대시보드 매매기록 탭 육안 확인
```
- 완료 기준: 지원 ETF 레버리지 거래가 기본 화면에서 즉시 환산(경고 없음), 미해소 6건만 별도.

## 롤백 방법
신규 code 39개는 백필 이전 `prices`에 존재하지 않았으므로, 해당 code만 삭제하면 완전 원복(기존 데이터 무영향):

```sql
-- Supabase SQL Editor에서 사용자가 실행. <code목록>=백필로 수집된 39개 code.
delete from prices
 where code in (<code목록>)
   and date between '2025-07-09' and '2026-07-10';
```
- 전체 삭제/truncate 금지. 워치리스트 종목(스킵 대상)은 code 목록에 없으므로 영향 없음.
- 정확한 code 목록은 실행 로그(`save_trade_symbol_prices` 요약)와 dry-run 로그에서 확보한다.

## 승인 필요 여부
**필요.** 위 실행 명령은 `prices`에 실제 write를 발생시킨다(약 8,520행 추가).
CLAUDE.md '실제 DB 변경은 명시적 승인 후에만 실행' 규칙에 따라, 사용자가 승인하면
스테이징에서 먼저 실행·검증한다. 이번 단계(코드·테스트·계획)에서는 실행하지 않았다.
