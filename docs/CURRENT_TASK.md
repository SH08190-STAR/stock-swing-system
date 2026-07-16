# CURRENT_TASK — 현재 활성 작업

> 이 문서는 **덮어쓰기** 문서다. 새 작업 시작 시 기존 내용을 누적하지 말고
> 아래 템플릿 전체를 새로 채운다. 작업이 없으면 상태를 `대기`로 둔다.

## 상태
대기  <!-- 대기 / 설계 / 구현 / 검수 / push 대기 / 완료 -->

## 직전 마일스톤 — 토스 Relay 운영 배포 **완료 (2026-07-17)**
- main = staging/ui-v3 = LKG = `4787186`. release tag `prod-toss-relay-live-20260717`,
  rollback tag `prod-pre-toss-relay-20260716`(→`3997bb6`), historical LKG `39b8c95`.
- Streamlit → Fly Relay(nrt, static egress IPv4) → Toss Open API 구조로 운영 중.
  US 화면만 Relay 활성, KR은 기존 Supabase/FDR 유지. 전체 pytest 363 passed.
- 운영 검증: Relay POST 4건 전부 200, 오류·AttributeError·segfault 0.
- 상세(아키텍처·보안 경계·시장 정책·부분 반환 정책·미해결 항목):
  docs/PROJECT_STATE.md "토스 Relay 운영" 섹션.

## 다음 목표 — Toss Relay 운영 안정화 관찰 및 후속 기능 우선순위 결정

### 1) 운영 안정화 관찰 (당분간 코드 변경 없이)
- 관찰 항목: Relay 502/429/timeout 발생 빈도, `/healthz` 연속성, Machine restart,
  월 비용(약 $5.6 예상 대비 실제), 미장 카드의 provider Toss 표시 안정성.
- 재발 시 판단 기준: 단발 502는 상류 일시 지연(부분 반환으로 흡수됨) →
  기록만. 연속 502·401·403은 **즉시 중단 후 진단**(credentials·허용 IP 확인).
- 금지: 근거 없는 Reboot·재배포, static egress IP release, Machine 2대 이상.

### 2) 후속 기능 우선순위 결정 (사용자 판단 필요)
후보 — 착수 전 사용자 승인 필요:
- **KR Toss 지원 검증**: Toss의 KR 심볼 포맷 확인(숫자 코드 지원 여부) +
  `_resolve_symbol`이 한글 종목명을 그대로 내보내는 문제 해결. 성공 시 국장 활성화.
- **거래대금 소스 전환**: pykrx/FDR이 거래대금 미제공 → data.go.kr 공공 API
  (API 키 발급 대기 중) — 분류 정확도에 직결.
- **과거 native segfault 근본 원인 규명**: 현재 fix 1 우회로 재현 없음. 우선순위 낮음.
- 기타 대시보드·분류 로직 개선.

## 이번 단계 제한 — 하지 않음
- 코드·테스트 변경, Fly deploy/Reboot/Secrets 변경, Streamlit Secrets 변경,
  DB write, tag 수정·삭제.

## DB write 허용 여부
아니오 (읽기 전용)

## push 허용 여부
문서 커밋만 허용(`docs: record Toss relay production release`). 기능 변경은 승인 후.
