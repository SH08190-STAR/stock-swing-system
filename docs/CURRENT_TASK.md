# CURRENT_TASK — 현재 활성 작업

> 이 문서는 **덮어쓰기** 문서다. 새 작업 시작 시 기존 내용을 누적하지 말고
> 아래 템플릿 전체를 새로 채운다. 작업이 없으면 상태를 `대기`로 둔다.

## 상태
push 대기

## 목표
매매기록의 본주 현재가와 레버리지 ETF 현재가를 서로 다른 출처·기준시각으로 섞어
계산하는 문제를 제거한다.

환산가와 수량 계산은 반드시 일관된 가격 쌍으로만 수행하고, 화면에 가격 출처와
기준시각을 표시한다.

향후 Toss Securities Open API를 연결할 수 있는 구조로 만들되, 현재는 Toss API를
실제 구현하지 않는다.

## 현재 확인된 문제

실제 화면 비교:

- PLTR
  - 토스증권: 약 $126.79
  - 우리 앱: 약 $129.04
- PLTU
  - 토스증권: $29.41
  - 우리 앱: $29.41
- TEM
  - 토스증권: 약 $58.23
  - 우리 앱: 약 $61.50
- TEMT
  - 토스증권: $24.40
  - 우리 앱: $24.40
- 삼성전자 본주도 토스증권과 우리 앱 가격 차이가 있으나 레버리지 ETF 가격은 일치

추정 원인:
- 본주 가격은 Supabase stocks.close 또는 과거 일봉 종가
- ETF 가격은 FDR fallback의 더 최근 값
- 서로 다른 시점의 가격을 2배 환산 공식에 동시에 사용

먼저 실제 코드를 분석해 정확한 원인을 확인하고, 확인되지 않은 가정으로 수정하지 마라.

## 핵심 원칙

레버리지 매매기록에서는 본주와 ETF 가격을 반드시 하나의 가격 쌍으로 취급한다.

금지되는 조합:
- 본주 = DB 종가
- ETF = FDR 최신값

허용되는 조합:
1. 본주와 ETF 모두 동일 외부 공급자
2. 본주와 ETF 모두 DB의 동일 거래일 가격

한쪽만 최신 가격 조회에 성공하면 다른 출처 가격을 섞지 않는다.

가격 쌍이 일관되지 않으면:
- 예상 환산가 표시하지 않음
- 수량 계산하지 않음
- `가격 기준 불일치` 안내 표시

## 구현 대상

### 1. 현재 가격 조회 흐름 분석

확인:
- latest_price()
- trade_price()
- 가격 새로고침
- _trade_calc()
- FDR fallback
- stocks.close 조회
- prices 최신 close 조회
- leverage_symbol 조회

분석 결과에서 본주와 ETF가 각각 어떤 출처로 조회되는지 명확히 기록한다.

### 2. 가격 스냅샷 구조 추가

권장 구조는 아래와 같으나 현재 코드에 맞게 최소 구현한다.

QuoteSnapshot:
- symbol
- price
- source
- asof
- market
- session 또는 price_type
- valid

QuotePair:
- base
- leverage
- is_consistent
- reason

클래스가 과하면 dict/dataclass/NamedTuple 중 가장 단순한 방식 사용.

### 3. 가격 공급 우선순위

레버리지 매매기록:

1순위:
- FDR 또는 현재 외부 조회 경로에서 본주와 ETF를 같은 실행 흐름으로 둘 다 조회
- 두 가격 모두 유효해야 함
- 마지막 거래일 또는 기준시각 확인
- 기준일이 다르면 일관되지 않은 것으로 처리

2순위:
- Supabase prices에서 본주와 ETF가 모두 존재할 경우
- 두 종목의 최신 공통 거래일 가격을 사용
- 각 종목의 개별 최신 날짜를 섞지 않음

실패:
- 한쪽 가격만 있으면 계산 보류
- DB 본주 + FDR ETF 혼합 금지
- FDR 본주 + DB ETF 혼합 금지

본주 단독 매매:
- 가격 쌍 문제가 없으므로 기존 우선순위를 유지할 수 있음
- 단, 출처와 기준시각은 표시

### 4. 최신 공통 거래일 처리

DB fallback을 사용할 때:

- 본주와 ETF prices 데이터에서 공통으로 존재하는 가장 최근 date를 찾는다.
- 같은 date의 close를 둘 다 사용한다.
- 공통 date가 없으면 계산하지 않는다.

stocks.close와 prices.close를 임의로 섞지 않는다.

### 5. 가격 새로고침

`🔄 가격 새로고침` 클릭 시:

- 본주와 ETF 가격 쌍 캐시를 함께 초기화
- 한쪽 캐시만 갱신되는 상황 금지
- 전체 앱 캐시는 지우지 말 것
- 관심종목·매매기록·섹터 캐시에 영향 주지 말 것

### 6. UI 표시

매매기록 카드에서:

- `본주 현재가`
- `거래 현재가 · ETF`
- 가격 출처
- 가격 기준시각 또는 기준일
- 가격 일관성 상태

예:

`가격 기준 2026-07-12 15:25 · FDR`

또는:

`가격 기준 2026-07-10 종가 · Supabase`

불일치 시:

`⚠ 본주와 ETF 가격 기준이 달라 예상 환산가 계산을 보류했습니다.`

기존 `환산` 문구는 `예상 환산가`로 변경한다.

환산 공식은 변경하지 않는다.

### 7. 향후 Toss API 연결 준비

현재는 Toss API 호출을 구현하지 않는다.

단, 나중에 다음 우선순위로 추가할 수 있도록 가격 조회 구조를 분리한다.

1. TossQuoteProvider
2. FDRQuoteProvider
3. DatabaseQuoteProvider

과도한 추상화 금지. 현재 작업에 필요한 최소 인터페이스만 만든다.

Toss API 키, 엔드포인트, 응답 구조를 추측하지 않는다.

## 계산 허용 조건

레버리지 환산가와 수량은 아래 조건을 모두 만족할 때만 계산:

- 본주 가격 존재
- ETF 가격 존재
- 둘 다 0보다 큼
- 출처 동일
- 기준 거래일 동일 또는 허용 가능한 동일 스냅샷
- 본주 현재가와 ETF 현재가가 같은 QuotePair에 속함

조건 불충족:
- 예상 환산가 None
- 수량 None
- UI `—`
- 이유 안내

## 데이터 보호

DB write: 아니오
push: 예 (사용자 승인 완료 — 2026-07-12)

금지:
- trade_records 수정·삭제
- stock_targets 수정·삭제
- prices/stocks 수정·삭제
- schema 변경
- 파이프라인 실행
- FORCE_RUN 실행
- GitHub Actions 변경
- Toss API 실제 호출
- 가격 데이터를 DB에 신규 저장
- 환산 공식 변경
- 수량 반올림 규칙 변경

## 읽을 파일

- CLAUDE.md
- docs/PROJECT_STATE.md
- docs/DECISIONS.md
- dashboard/app.py
- app/database.py
- app/collector.py에서 FDR 조회 관련 부분만
- tests/test_trades.py
- tests/test_dashboard.py

전체 저장소 탐색 금지.

## 수정 허용 파일

- docs/CURRENT_TASK.md
- dashboard/app.py
- app/database.py
- tests/test_trades.py
- tests/test_dashboard.py

app/database.py는 공통 거래일 조회가 필요한 경우에만 최소 수정.

## 수정 금지 파일

- app/collector.py
- scripts/run_daily_update.py
- scripts/schema.sql
- CSV
- requirements.txt
- GitHub Actions

## 테스트

최소 테스트:

1. 같은 FDR 출처의 본주+ETF 가격 쌍은 계산 허용
2. 본주 FDR + ETF DB 조합은 계산 금지
3. 본주 DB + ETF FDR 조합은 계산 금지
4. DB에서 같은 거래일 가격 쌍은 계산 허용
5. DB에서 최신 거래일이 서로 다르면 최신 공통 거래일 사용
6. 공통 거래일이 없으면 계산 금지
7. 한쪽 가격만 존재하면 계산 금지
8. 본주 단독 매매 계산은 기존 동작 유지
9. 가격 새로고침 시 쌍 캐시가 함께 초기화
10. UI에 출처와 기준일 표시
11. 불일치 시 예상 환산가·수량이 `—`
12. 기존 환산 공식과 일반 반올림 유지
13. 전체 기존 테스트 통과

명령:

```
py -3.12 -m py_compile dashboard/app.py app/database.py
py -3.12 -m pytest -q tests/test_trades.py tests/test_dashboard.py
py -3.12 -m pytest -q
```

로컬 Streamlit:

```
py -3.12 -m streamlit run dashboard/app.py --server.port 8501
```

## 완료 조건

- health 200
- PLTR/PLTU 같은 레버리지 기록에서 가격 출처가 한 쌍으로 표시
- TEM/TEMT도 동일
- 삼성전자/레버리지 ETF도 동일
- 혼합 가격으로 환산하지 않음
- 기존 매매기록 기능 정상
- DB write 없음
- push 없음
