---
name: force-run-verify
description: FORCE_RUN=1로 일일 파이프라인을 1회 강제 실행하고 실행 전후 DB 상태를 검증한다. 사용자가 명시적으로 승인했을 때만 사용.
---

# /force-run-verify — 파이프라인 강제 실행 검증

## 실행 조건

- 사용자의 **명시적 승인이 없으면 실행 금지.** 승인 문구가 없으면
  실행하지 않고 승인이 필요함을 보고한다.

## 실행 전 (read-only)

1. 관련 테스트가 통과 상태인지 확인 (필요 시 관련 테스트만 실행).
2. DB 기준값을 read-only로 기록:
   stocks, prices, trade_records, stock_targets의 핵심 count.

## 실행

3. FORCE_RUN을 설정해 **정확히 1회** 실행:
   `$env:FORCE_RUN = '1'; py -3.12 scripts/run_daily_update.py > .tmp/pipeline.log 2>&1`
4. 오류가 나도 **임의 재실행 금지** — 로그를 분석해 보고하고 멈춘다.
5. 실행 후 환경변수 해제 확인: `Remove-Item Env:FORCE_RUN`

## 실행 후 검증

6. 4개 테이블 핵심 count를 다시 조회해 실행 전과 비교한다.
7. **trade_records 또는 stock_targets에 변화가 있으면 즉시 경고**하고
   추가 작업을 멈춘다 (이 테이블들은 파이프라인이 건드리면 안 됨).
8. delete, truncate는 어떤 경우에도 실행하지 않는다.

## 보고

- 파이프라인 로그 전문은 `.tmp/pipeline.log`에 두고 요약만 보고:
  실행 결과, 테이블별 count 변화, 이상 여부.
- 검증이 끝나도 별도 승인 전에는 push하지 않는다.
