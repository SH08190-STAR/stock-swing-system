---
name: incident-response
description: 운영(Streamlit Cloud) 장애 발생 시 로그 확보→오류 분류→재현→단일 조치 순서로 대응한다. 앱 crash, segfault, 배포 실패, health 실패 보고 시 사용.
---

# /incident-response — 운영 장애 대응

docs/INCIDENT_PLAYBOOK.md의 실행 절차다. 순서를 건너뛰지 않는다.

## 절대 규칙

- **원인 확인 전 push·revert·Reboot 금지** (Cloud 일시 장애 판정 시 Reboot 1회만 예외)
- 한 번에 **하나의 변수만** 변경하고 결과를 확인한 뒤 다음 판단
- 같은 조치 2회 반복 금지 (Reboot 최대 1회 포함)
- 현재 운영 앱이 정상이면 어떤 재배포·Reboot도 하지 않는다

## 절차

1. **로그 우선 확보**: 어떤 조치보다 먼저 Cloud 로그를
   `.tmp/incident_<YYYY-MM-DD>_<n>.log`로 저장한다.
   Reboot하면 로그가 사라진다.
2. **오류 분류**: INCIDENT_PLAYBOOK.md §1 표에 따라
   A(traceback) / B(segfault) / C(install 실패) / D(Cloud 일시 장애)로 판정한다.
   분류 전에는 어떤 변경도 하지 않는다.
3. **git commit 확인**: `git log --oneline -10`으로 최근 배포 커밋과
   docs/PROJECT_STATE.md의 LAST_KNOWN_GOOD_COMMIT을 비교하고,
   장애 시점 이후 들어간 변경을 특정한다.
4. **로컬/스테이징 재현**: INCIDENT_PLAYBOOK.md §2 순서로 재현한다.
   운영 앱으로 실험하지 않는다. 재현 실패 시 분류로 돌아간다.
5. **단일 조치**: 원인 후보가 확정되면 조치 1개만 실행하고
   결과를 기록한다. 사용자 승인 없이 push하지 않는다.
6. **종료**: health 200 + 10분 안정 확인
   (`py -3.12 scripts/cloud_smoke_check.py --url <URL> --stability-minutes 10`),
   사건 문서를 `docs/incidents/`에 작성한다.

## 보고 규칙

- 정상 완료 보고는 **400자 이내**
- **전체 로그를 채팅에 출력하지 않는다** — 핵심 줄만 인용하고
  전문은 .tmp/에 저장
- 확정되지 않은 원인을 확정적으로 보고하지 않는다 ("추정"으로 구분)
- 실행하지 않은 조치를 완료했다고 보고하지 않는다
