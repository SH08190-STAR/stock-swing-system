# CLAUDE.md — stock-swing-system 고정 규칙

## 프로젝트
- 프로젝트명: stock-swing-system (한국주식 단기스윙 자동분류 시스템)
- Python 명령은 `py -3.12` 사용
- 기본 브랜치: main
- 상세 상태는 필요할 때만 docs/PROJECT_STATE.md, docs/CURRENT_TASK.md,
  docs/DECISIONS.md를 읽는다 (이 파일에서 @import 하지 않음)

## 안전 규칙 (절대)
- 사용자 승인 전 push 금지
- 실제 DB 변경(write/migration)은 명시적 승인 후에만 실행
- trade_records, stock_targets 기존 데이터 삭제·초기화·일괄수정 금지
- prices, stocks 테이블 truncate 금지
- .env, API key, token, secret 커밋 금지

## 작업 범위
- 수정 범위 밖 파일은 필요성이 확인될 때만 읽는다
- 전체 저장소 재탐색 금지 — docs 상태 문서를 우선 사용
- CURRENT_TASK.md에 없는 기능을 임의로 추가하지 않는다

## 테스트
- 구현 중: 관련 테스트만 실행
- 완료 시: 전체 테스트 1회 (`py -3.12 -m pytest -q`)
- 긴 출력은 .tmp/ 에 저장: pytest → .tmp/pytest.log,
  파이프라인 → .tmp/pipeline.log, 긴 diff → .tmp/current.diff

## 보고 형식
- 정상 완료 보고는 400자 이내
- 명령 출력·diff·성공 로그 전문을 채팅에 출력하지 않는다
- 실패 시에만 오류 핵심과 필요한 로그 부분만 제공

## Compact 지침
- 보존: 현재 목표, 변경 파일 목록, 미해결 문제, 테스트 결과,
  DB write 여부, push 여부
- 제거: 반복 설명, 성공 로그 전문, 오래된 터미널 출력
