# DECISIONS — 변하지 않는 결정 기록

> 확정된 설계 결정만 기록한다. 작업 과정·임시 해결책은 넣지 않는다.

## 매매 계산
- 레버리지 계산은 2배 고정
- 수량 계산은 `floor(x + 0.5)` 방식의 일반 반올림
- 본주 단독 매매도 동일하게 리스크·수량 계산을 적용
- 완료 매매의 총손익은 (청산가 − 진입가) × 수량 합산 방식으로 계산

## 종목·데이터 기준
- 한국 종목 코드는 6자리 문자열로 취급 (leading zero 보존, 예: "005490")
- POSCO Holdings는 한국 본주 005490 유지 — PKX(ADR)로 바꾸지 않는다
- 단기스윙 분류 기준: 최근 6개월 일평균 거래대금 1,000억 원 이하
- 가격 수집 기간은 12개월
- 52주 고점은 최근 365일 **장중 High** 기준
- High 결측 행은 close 값으로 fallback
- 신규상장 종목은 보유 기간 내 고점을 사용

## UI·기능
- 관심가(target price) UI는 숨기되, stock_targets 데이터와 관련 함수는 보존
- 섹터 카드는 waiting / entered / tp_in 상태의 매매기록과 연동

## 데이터 보호 원칙
- trade_records, stock_targets 기존 데이터 삭제·초기화·일괄수정 금지
- prices, stocks truncate 금지
- 실제 DB write는 사용자 명시 승인 후에만

## 운영 방식
- Supabase 스키마 변경은 컬럼 추가(additive) 우선,
  SQL은 사용자가 Supabase에서 직접 실행하는 방식
- 로컬 검수 완료 후, push는 별도 승인을 받아 진행
