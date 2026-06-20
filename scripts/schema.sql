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
    classification  text not null,        -- swing / sector / hold
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
