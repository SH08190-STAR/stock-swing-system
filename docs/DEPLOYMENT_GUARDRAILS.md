# DEPLOYMENT_GUARDRAILS — 배포 안전장치

> main push = Streamlit Cloud 운영 배포다. 이 문서의 절차를 생략하지 않는다.

## 배포 순서 (고정)

1. **기능 브랜치**에서 구현·커밋 (main 직접 커밋 금지)
2. `py -3.12 scripts/predeploy_check.py` 전체 통과
3. **스테이징 확인**: 별도 Streamlit Cloud 앱(스테이징) 또는 로컬 서버에
   해당 브랜치를 배포/실행
4. **10분 안정 확인**: `py -3.12 scripts/cloud_smoke_check.py --url <스테이징URL> --stability-minutes 10`
   (로컬이면 predeploy_check의 120초 생존 검사 + 수동 10분 관찰로 대체)
5. 사용자 승인 후 main merge → push (push는 /safe-push 절차)
6. 배포 후: `deploy-smoke` workflow 결과 확인, 실패 시 INCIDENT_PLAYBOOK.md로 이동
7. 운영 정상 확인되면 docs/PROJECT_STATE.md의 LAST_KNOWN_GOOD_COMMIT 갱신

## LAST_KNOWN_GOOD_COMMIT 관리

- 위치: docs/PROJECT_STATE.md
- 정의: 운영(Streamlit Cloud)에서 **정상 동작이 확인된** 가장 최근 main 커밋
- 갱신 시점: 배포 후 smoke check 통과 + 10분 이상 안정 확인 후에만
- 장애 시 rollback 목적지는 항상 이 커밋이다. 추측으로 갱신하지 않는다.

## 배포 전 체크리스트

- [ ] 작업 트리 clean (`git status`)
- [ ] `scripts/predeploy_check.py` 전체 PASS (테스트·compile·서버 120초 생존 포함)
- [ ] requirements.txt 변경이 있으면 스테이징에서 먼저 검증했는가
- [ ] secret/.env가 커밋에 포함되지 않았는가
- [ ] LAST_KNOWN_GOOD_COMMIT이 최신인가 (rollback 목적지 확보)
- [ ] 사용자 push 승인 있음

## 배포 후 체크리스트

- [ ] Streamlit Cloud 재배포 완료 확인 (약 2~5분 소요)
- [ ] health 200 확인 (`/_stcore/health`)
- [ ] 10분 안정 확인 (deploy-smoke workflow 또는 수동 smoke check)
- [ ] 대시보드 주요 화면 1회 육안 확인
- [ ] 정상이면 LAST_KNOWN_GOOD_COMMIT 갱신

## Rollback 기준

다음 중 하나면 rollback을 **검토**한다 (원인 확인이 우선, INCIDENT_PLAYBOOK 참조):

- 배포 후 30분 내 앱 crash/segfault가 2회 이상 재현
- health 실패가 연속 3회 이상 지속
- 데이터 표시 오류로 매매 판단에 영향

Rollback 방법: `git revert`로 **문제 커밋 하나만** 되돌리거나,
LAST_KNOWN_GOOD_COMMIT 기준 브랜치를 만들어 검증 후 배포한다.

## Reboot / Revert 제한 (절대)

- **현재 운영 앱이 정상이면 Reboot·revert·재배포하지 않는다.**
- Streamlit Cloud Reboot는 장애당 **최대 1회**. 1회로 해결되지 않으면
  Reboot 반복 대신 로그 확보·원인 분류로 전환한다 (INCIDENT_PLAYBOOK).
- **연쇄 revert 금지**: revert는 원인으로 지목된 커밋 1개만 대상으로 한다.
  "일단 다 되돌려보기"는 2026-07-12 사건에서 확인된 낭비 패턴이다
  (docs/incidents/2026-07-12-streamlit-segfault.md).
- revert 후에도 실패하면 추가 revert 전에 반드시 원인 재분류를 한다.

## 변경 격리 원칙

- 한 배포에 한 종류의 변경만 싣는다 (기능 / 의존성 / 설정 혼합 금지)
- requirements 변경은 단독 커밋 + 스테이징 검증 필수
  (계획: docs/DEPENDENCY_LOCK_PLAN.md)

## 부분 hot-reload 주의 (여러 모듈 동시 변경 배포)

- **health 200은 import된 하위 모듈의 런타임 정합성을 보장하지 않는다.** `/_stcore/health`는
  서버 프로세스 생존만 확인할 뿐, dashboard가 부르는 app.database/app.quotes가 최신 버전인지는
  검증하지 못한다.
- 여러 Python 모듈이 한 배포에서 동시에 바뀌었는데 Streamlit Cloud가 "Updated app"만 표시하면,
  최상위 스크립트만 새로 rerun하고 하위 모듈을 구버전으로 남기는 **부분 hot-reload** 가능성을
  점검한다(증상: 배포 커밋에 존재하는 함수에 대한 AttributeError). → docs/INCIDENT_PLAYBOOK.md A-2.
- 완화책: 앱에 런타임 모듈 정합성 가드(계약 검사 + 1회 reload 자동 복구)를 두었다
  (dashboard/app.py `check_and_recover_modules`, app.*의 `MODULE_API_VERSION`). 모듈 API가 바뀌는
  배포에서는 해당 버전을 올려 가드가 불일치를 감지하게 한다.
