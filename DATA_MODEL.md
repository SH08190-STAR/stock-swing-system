# DATA_MODEL.md — 데이터 모델 (Supabase / PostgreSQL)

DDL 원본은 `scripts/schema.sql`. 아래는 설계 설명.

## 1. stocks — 종목 현재 상태 (종목당 1행)

| 필드 | 자료형 | 설명 |
|---|---|---|
| code | text **PK** | 종목코드(한국 6자리) / 해외 티커 |
| name | text | 종목명 |
| country | text | KR / US / … |
| market | text | KOSPI / KOSDAQ / NASDAQ … |
| origin_sector | text | 기존 산업 섹터 |
| origin_sub | text | 기존 세부섹터 |
| tier | text | mega/core/growth/theme |
| classification | text | swing / sector / hold (해외·M7은 고정) |
| avg_6m | bigint | 최근 6개월 일평균 거래대금(원) |
| short_avg | bigint | 최근 20거래일 평균 거래대금(원) |
| today_value | bigint | 당일 거래대금(원) |
| close | double precision | 현재가(종가) |
| change_pct | double precision | 전일 대비 % |
| used_days | int | 평균 계산에 쓴 유효 거래일 수 |
| estimated | boolean | FDR 근사 거래대금 포함 여부 |
| swing_since | date | 단기스윙 최초 편입일 |
| data_date | date | 데이터 기준일 |
| updated_at | timestamptz | 마지막 갱신 시각 |
| reason | text | 보류/근사 사유 |

- **중복 방지**: PK=code. upsert(on_conflict=code).
- **보존 규칙**: hold 시 avg_6m 등 수치가 None이면 그 필드는 **갱신 제외**(이전 정상값 유지).

## 2. prices — 일별 시세 (시계열)

| 필드 | 자료형 | 설명 |
|---|---|---|
| code | text | 종목코드 |
| market | text | 시장 |
| date | date | 거래일 |
| open / high / low / close | double precision | 시·고·저·종가 |
| volume | double precision | 거래량 |
| value | double precision | 거래대금(원) |
| value_estimated | boolean | 근사값 여부 |

- **기본키(복합)**: (code, date) → **동일 일봉 중복 저장 방지**.
- **인덱스**: `idx_prices_code_date (code, date desc)` — 6개월 범위 조회 가속.
- upsert(on_conflict="code,date").

## 3. (분류 상태) — stocks 테이블이 겸함

별도 테이블을 두지 않고 `stocks.classification`이 현재 분류를 보유.
시점별 분류는 `history`로 추적.

## 4. history — 분류 변경 이력

| 필드 | 자료형 | 설명 |
|---|---|---|
| id | bigserial **PK** | |
| change_date | date | 변경일 |
| code | text | 종목코드 |
| name | text | 종목명 |
| from_class | text | 이전 분류 |
| to_class | text | 변경 후 분류 |
| prev_avg_6m | bigint | 이전 6개월 평균 |
| new_avg_6m | bigint | 최신 6개월 평균 |
| reason | text | 변경 사유 |
| created_at | timestamptz | 기록 시각 |

- **인덱스**: `idx_history_date (change_date desc)`.
- **외래키(논리적)**: code → stocks.code (실제 FK는 신규상장 타이밍 이슈로 선택. 권장: 미설정 또는 ON DELETE SET NULL).
- **중복 방지**: 같은 (code,change_date,to_class)이 이미 있으면 재기록 금지(애플리케이션 레벨에서 직전 분류와 다를 때만 insert).

## 5. runs — 실행 기록 (권장 추가)

| 필드 | 자료형 | 설명 |
|---|---|---|
| id | bigserial **PK** | |
| run_at | timestamptz | 실행 시각 |
| data_date | date | 처리한 거래일 |
| collected | int | 수집 성공 종목 수 |
| swing_total | int | 전체 단기스윙 수 |
| hold_total | int | 보류 수 |
| status | text | ok / partial / failed / skipped(휴장) |
| note | text | 비고 |

> 원 요구의 "실행 기록 테이블"에 해당. 운영 모니터링·재실행 판단에 사용.

## 6. errors — 오류 기록

| 필드 | 자료형 | 설명 |
|---|---|---|
| id | bigserial **PK** | |
| occurred_at | timestamptz | 오류 시각 |
| target | text | 오류 대상(종목/단계) |
| cause | text | 원인 |
| retried | text | 재시도 결과 |
| last_ok_update | text | 마지막 정상 업데이트 시각 |

## 7. meta — key-value

| key | value 예 |
|---|---|
| last_ok_update | 2026-06-20 16:45 |
| last_data_date | 2026-06-20 |

## 8. 인덱스 권장 요약

- `prices (code, date desc)` — 시계열 범위 조회
- `history (change_date desc)` — 최신 이력
- `stocks (classification)` — 분류별 필터(선택)
- `stocks (avg_6m desc)` — 거래대금 순위(선택)

## 9. 자료형 주의

- 거래대금/금액은 **bigint(원 단위 정수)**. 1,000억 = 100000000000 (int 안전).
- 가격·등락률은 double precision.
- 날짜는 date, 시각은 timestamptz(UTC 저장, 표시 시 KST 변환).
