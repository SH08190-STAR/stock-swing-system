# CURRENT_TASK — 현재 활성 작업

> 이 문서는 **덮어쓰기** 문서다. 새 작업 시작 시 기존 내용을 누적하지 말고
> 아래 템플릿 전체를 새로 채운다. 작업이 없으면 상태를 `대기`로 둔다.

## 상태
push 대기  <!-- 대기 / 설계 / 구현 / 검수 / push 대기 -->

## 목표
Streamlit Cloud 장애 재발 시 운영 서비스 중단과 반복 대응을 막기 위한
배포 안전장치와 장애 대응 체계를 구축한다.

## 중요 제약
- 앱 기능, DB, CSV, 가격 계산 로직은 변경하지 않는다
- 현재 운영 앱이 정상일 때는 Reboot·revert·재배포하지 않는다
- 이번 작업은 운영 문서, 검증 스크립트, CI, Claude Skill만 만든다
- push는 사용자 승인 완료 (2026-07-13) — 안전장치 파일만 커밋

## 구현 항목

### 1. docs/DEPLOYMENT_GUARDRAILS.md
- 기능 브랜치 → 스테이징 → 10분 안정 확인 → main 순서
- LAST_KNOWN_GOOD_COMMIT 관리
- 배포 전/후 체크리스트
- rollback 기준
- Reboot 최대 1회
- 연쇄 revert 금지

### 2. docs/INCIDENT_PLAYBOOK.md
- Python traceback / Segmentation fault / dependency install 실패 /
  Cloud 일시 장애를 구분하는 절차
- 로그 저장 형식
- 재현 순서
- 단일 조치 원칙

### 3. docs/incidents/2026-07-12-streamlit-segfault.md
- 이번 사건의 사실만 기록
- 확정되지 않은 원인을 확정적으로 쓰지 않기
- 실행한 조치와 결과 기록
- 낭비된 반복 대응 방지사항 기록

### 4. .claude/skills/incident-response/SKILL.md
- 로그 우선 확보
- 오류 분류
- git commit 확인
- 로컬/스테이징 재현
- 한 번에 하나의 변수만 변경
- 정상 보고 400자 이내
- 전체 로그 채팅 출력 금지
- 원인 확인 전 push/revert/reboot 금지

### 5. scripts/predeploy_check.py
검사 항목:
- git status
- secret 패턴
- py_compile
- 전체 테스트
- requirements 설치 가능 여부
- pip check
- Streamlit 서버 실행
- health 200
- 최소 120초 생존
- 종료코드와 결과 요약
- 긴 출력은 .tmp에 저장

### 6. scripts/cloud_smoke_check.py
입력: 앱 URL
동작:
- 배포 대기
- health endpoint 반복 확인
- 최소 10분 안정성 검사 옵션
- 실패 시 시각·HTTP 상태·연속 실패 수 기록
- secret 출력 금지

### 7. .github/workflows/deploy-smoke.yml
- main push 후 실행
- 적절한 대기 후 smoke script 실행
- 실패 시 workflow 실패 처리
- 앱 URL은 repository variable 또는 secret 사용
- DB write 없음

### 8. 의존성 고정 감사
- 현재 requirements.txt의 direct dependency와 설치된 실제 버전 비교
- 즉시 대량 pin하지 말고 docs/DEPENDENCY_LOCK_PLAN.md에
  안전한 잠금 계획만 작성
- runtime/dev dependency 분리안 제시
- 스테이징 검증 전 requirements 변경 금지

### 9. docs/PROJECT_STATE.md
- LAST_KNOWN_GOOD_COMMIT 필드 추가
- 현재 운영 안정 커밋은 실제 git 상태와 사용자 제공 사실을 기준으로 기록
- 추측 금지

## 수정 허용 파일
- docs/
- .claude/skills/incident-response/SKILL.md
- scripts/predeploy_check.py
- scripts/cloud_smoke_check.py
- .github/workflows/deploy-smoke.yml
- docs/PROJECT_STATE.md
- tests/ (신규 스크립트 테스트 추가 가능)

## 수정 금지 파일
- dashboard/app.py
- app/
- schema.sql
- CSV
- requirements.txt
- DB
- Streamlit Cloud 설정

## DB write 허용 여부
아니오

## push 허용 여부
예 (사용자 승인 — 커밋 메시지: chore: add deployment guardrails and incident workflow)

## 검증
- 신규 Python 스크립트 py_compile
- 신규 스크립트 단위 테스트
- YAML 문법 검사
- git diff --check
- 앱 코드·DB·CSV·requirements 미변경 확인
- 전체 앱 pytest는 앱 코드 미변경이므로 실행하지 않아도 됨

## 미해결 사항
- Streamlit 1.59.x segfault 원인 추적 및 업그레이드 재시도는 별도 작업
