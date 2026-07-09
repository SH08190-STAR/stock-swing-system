-- schema.sql — Supabase(PostgreSQL) 테이블 정의
-- Supabase 대시보드 > SQL Editor 에 붙여넣고 한 번 실행하면 된다.

-- 1) 종목 현재 상태 (종목당 1행)
create table if not exists stocks (
    code            text primary key,
    name            text not null,
    market          text,                 -- KOSPI / KOSDAQ
    origin_sector   text,                 -- 기존 산업 섹터
    origin_sub      text,                 -- 기존 세부섹터
    tier            text,                 -- mega/core/growth/theme
    classification  text not null,        -- swing / sector / hold / global(해외 표시용)
    high_52w        double precision,     -- 최근 52주 고점(장중 고가 기준, 일일 파이프라인이 캐시)
    avg_6m          bigint,               -- 최근 6개월 일평균 거래대금(원)
    short_avg       bigint,               -- 최근 20일 평균 거래대금(원)
    today_value     bigint,               -- 당일 거래대금(원)
    close           double precision,     -- 현재가(종가)
    change_pct      double precision,     -- 전일 대비 %
    used_days       int,                  -- 평균 계산에 쓴 거래일 수
    estimated       boolean default false,-- FDR 근사 거래대금 포함 여부
    data_date       date,                 -- 데이터 기준일
    updated_at      timestamptz,          -- 최신화 시각
    reason          text                  -- 보류/근사 사유 등
);

-- 2) 일별 시세 (시계열, (code,date) 유니크 → 중복 저장 방지)
create table if not exists prices (
    code            text not null,
    market          text,
    date            date not null,
    close           double precision,
    high            double precision,     -- 장중 고가(52주 고점 계산용, 구데이터는 NULL 허용)
    volume          double precision,
    value           double precision,     -- 거래대금(원)
    value_estimated boolean default false,
    primary key (code, date)
);
create index if not exists idx_prices_code_date on prices(code, date desc);

-- 3) 분류 변경 이력
create table if not exists history (
    id           bigserial primary key,
    change_date  date not null,
    code         text not null,
    name         text,
    from_class   text,                    -- 이전 분류
    to_class     text,                    -- 변경 후 분류
    prev_avg_6m  bigint,                  -- 이전 평균 거래대금
    new_avg_6m   bigint,                  -- 최신 평균 거래대금
    reason       text,
    created_at   timestamptz default now()
);
create index if not exists idx_history_date on history(change_date desc);

-- 4) 오류 로그
create table if not exists errors (
    id              bigserial primary key,
    occurred_at     timestamptz default now(),
    target          text,                 -- 오류 대상(종목/단계)
    cause           text,                 -- 원인
    retried         text,                 -- 재시도 결과
    last_ok_update  text                  -- 마지막 정상 업데이트 시각
);

-- 5) 메타 (마지막 업데이트 시각 등 key-value)
create table if not exists meta (
    key    text primary key,
    value  text
);

-- 6) 관심가 (종목당 단일 관심가 — 사용자 입력값 영구저장)
-- 수집/분류 파이프라인과 독립. watchlist.csv 에는 넣지 않고 여기로 분리한다.
-- symbol 은 watchlist.symbol / stocks.code 와 동일한 값(한국 6자리 코드 또는 해외 티커).
-- 1인 사용자 기준이라 user_id 없음. 추후 note/is_active/band_low/band_high/alert_enabled 확장 가능.
create table if not exists stock_targets (
    symbol        text primary key,         -- 종목코드/티커 (stocks.code 와 동일)
    target_price  numeric not null,         -- 관심가(원)
    created_at    timestamptz default now(),
    updated_at    timestamptz default now()
);

-- 7) 매매 기록 (국장/미장 × 대기중/진입/TP IN/완료 — 사용자 입력 매매 계획·진행)
-- 레버리지 환산가는 저장하지 않고 화면에서 자동 계산(2배 고정 규칙).
-- 완료 손익(realized_*)은 1차 MVP에서 수동 입력(익절 비중 규칙 확정 후 자동화 예정).
create table if not exists trade_records (
    id             uuid primary key default gen_random_uuid(),
    market_group   text not null,        -- KR(국장) / US(미장)
    status         text not null,        -- waiting / entered / tp_in / completed
    record_date    date not null,
    symbol         text not null,        -- 본주 티커/코드
    leverage_symbol text,                -- 레버리지 ETF명(티커)
    entry1 numeric, entry2 numeric, entry3 numeric, entry4 numeric,
    tp1 numeric, tp2 numeric,
    stop numeric,
    risk1 numeric, risk2 numeric, risk3 numeric, risk4 numeric,
    realized_tp1_profit numeric,         -- 1차 익절 수익(수동)
    realized_tp2_profit numeric,         -- 2차 익절 수익(수동)
    realized_stop_loss  numeric,         -- 손절액(수동)
    realized_total_pnl  numeric,         -- 총 손익(수동)
    memo text,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);
create index if not exists idx_trade_records_group_status
    on trade_records(market_group, status);
