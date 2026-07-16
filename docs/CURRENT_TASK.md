# CURRENT_TASK — 현재 활성 작업

> 이 문서는 **덮어쓰기** 문서다. 새 작업 시작 시 기존 내용을 누적하지 말고
> 아래 템플릿 전체를 새로 채운다. 작업이 없으면 상태를 `대기`로 둔다.

## 상태
검수  <!-- 대기 / 설계 / 구현 / 검수 / push 대기 / 완료 -->

## 목표 — Toss 가격 응답 부분 반환 견고화 (foundation per-item skip)
> 배경: staging Relay 활성 직후 미장 TP IN batch에서 502 3건 관측(07:22~07:23Z).
> 진단 결과 credentials/OAuth/IP/Relay 인증 정상, 동일 batch가 이후 200 —
> 원인은 일시적 데이터 지연 종목(소형 레버리지 ETF)의 불량 item 1개가
> app/toss.py의 all-or-nothing 파싱으로 batch 전체를 TossResponseError
> (→Relay 502 TOSS_BAD_RESPONSE)로 만든 구조.

- 브랜치: feature/toss-relay-partial-results (기준 staging/ui-v3=007a7d8)
- 변경(3파일, +127/−11):
  - app/toss.py — _parse_price_items를 item 단위 격리(_parse_one_price_item):
    컨테이너 오류(JSON·result 형식)는 기존 TossResponseError 유지, 개별 item
    불량(비dict·symbol 누락·null/0/음수/비숫자 가격·timestamp 누락/파싱불가/naive)
    은 그 item만 skip하고 정상 item 반환. 빈 result는 정상 {}. 항목이 있는데
    유효 0개면 TossResponseError(전체 손상 은폐 금지). HTTP/upstream 오류
    (401/403/404/429/5xx/timeout/OAuth/IP) 매핑은 전부 무변경.
  - tests/test_toss.py — 부분 반환 12건 추가(불량 유형 9종 parametrize·
    정상 2+불량 1·빈 result·전부 불량 raise·Decimal/개별 timestamp 보존·
    원본 값/secret 비노출). 기존 25건 계약 유지.
  - tests/test_toss_relay.py — 3건 추가(부분 dict → 200 + placeholder 없음·
    빈 dict → 200 빈 prices·전부 불량 → 502 TOSS_BAD_RESPONSE 유지).
- 무변경: Relay main/config·toss_relay_client·toss_overlay·dashboard·
  requirements·Dockerfile·workflows·Relay API schema·오류 매핑·DB fallback.
- 금지 준수: 심볼별 재호출·bisect·retry·sleep·negative cache·whitelist·
  특정 티커 예외 처리 없음.

## 검증 결과 (로컬, 2026-07-16)
- py_compile OK. toss 4개 파일 168 passed. 전체 pytest **353 passed**
  (직전 338 + 신규 15, .tmp/pytest.log). 회귀 0. git diff --check clean.
- 실제 Relay/Toss 네트워크 0회(전부 FakeSession/FakeTossClient)·DB 접근 0회.
- 배포 필요: 이 수정은 Relay 이미지에 포함되는 app/toss.py이므로
  **commit·push 후 Fly Relay 재배포가 있어야 운영에 반영**된다(승인 대기).

## DB write 허용 여부
아니오 (읽기 전용 — DB 접근 없음)

## push 허용 여부
아니오 (commit·push·Fly deploy 금지 — 사용자 승인 대기)
