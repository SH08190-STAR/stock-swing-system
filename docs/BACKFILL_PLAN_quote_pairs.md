# BACKFILL PLAN — 레버리지 ETF 가격 백필 (quote-pair v2)

> 목적: 활성 trade_records의 본주·레버리지 ETF 가격을 `prices`에 채워
> 레버리지 거래가 DB 동일 기준일 쌍으로 자동 환산되게 한다.
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
