---
name: supabase-migration
description: Supabase 스키마 변경을 additive 방식으로 준비하고 사용자가 SQL을 직접 실행하도록 안내한다. 스키마 변경이 필요할 때 사용.
---

# /supabase-migration — 스키마 변경 절차

## 원칙

- 기존 스키마와 데이터 보호가 최우선. 변경 전 영향 범위를 먼저 확인한다.
- 가능하면 **additive migration만** 사용한다 (컬럼 추가, 테이블 추가).
- truncate, drop, 기존 행 일괄 update 금지.
- trade_records, stock_targets 기존 데이터는 어떤 경우에도 건드리지 않는다.

## 절차

1. `scripts/schema.sql`에서 현재 정의를 확인한다.
2. 변경이 기존 데이터에 미치는 영향을 확인하고,
   기존 행의 새 컬럼이 NULL로 유지되는지 여부를 명시한다.
3. 실행용 SQL을 **별도 코드 블록**으로 제공한다
   (사용자가 Supabase SQL Editor에서 직접 실행).
4. 동일한 정의를 `scripts/schema.sql`에 반영한다.
5. 사용자가 "SQL 실행 완료"를 확인해 주기 전에는
   실제 저장 로직(app 코드의 DB write 경로) 검수·구현을 진행하지 않는다.

## 금지

- 사용자 SQL 실행 확인 전 push 금지
- Claude가 직접 DB에 DDL 실행 금지 (사용자 실행 방식 고정)
- 파괴적 문장(drop/truncate/일괄 update) 제안 금지

## 보고

제공한 SQL 요약, NULL 유지 여부, schema.sql 반영 여부만 간결히 보고한다.
