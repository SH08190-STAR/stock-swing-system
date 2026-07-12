# 2026-07-12 Streamlit Cloud Segmentation fault

## 증상 (사실만)

- Streamlit Cloud에서 앱 시작 후 약 2분 뒤 프로세스가 Segmentation fault로 종료
- Python traceback 없음 (Cloud 로그 기준)
- 로컬 환경에서는 재현되지 않음: py_compile OK, 전체 테스트 통과,
  health 200 정상

## 환경 (버전·커밋)

- Cloud: Python 3.12.13, streamlit 1.59.1
  (당시 requirements.txt가 `streamlit>=1.30`으로 미고정 → 최신 버전 설치됨)
- 로컬: streamlit 1.58.0 (정상 동작)
- 장애 인지 시점의 배포 커밋: 정확히 기록되지 않음
  (당일 06:49 `6369ae8 feat: refine dashboard spacing`이 장애 전 마지막 기능 push)

## 타임라인 (git 기록 기준, KST)

| 시각 | 조치 | 결과 |
|---|---|---|
| 07-12 06:49 | `6369ae8` feat: refine dashboard spacing push | 이후 Cloud에서 segfault 발생 (정확한 발생 시각 미기록) |
| (기록 없음) | Cloud Reboot 시도 (횟수 미기록) | 해소되지 않음 |
| 07-12 15:18 | `974494e` fix: pin Streamlit runtime version (`streamlit==1.58.0`) push | — |
| 07-12 16:25 | `f4babe9` feat: enforce consistent trade quote pairs push | — |
| 07-12 16:48 | `c2acfc9` Revert "feat: enforce consistent trade quote pairs" | — |
| 07-12 17:04 | `9975719` Revert "feat: refine dashboard spacing" | — |
| 07-13 | main @ `9975719` 상태에서 운영 정상 (사용자 확인) | 안정 |

주: Cloud 로그가 보존되지 않아 각 push 직후의 Cloud 상태(성공/실패)는
개별적으로 확인할 수 없다. 위 표의 조치와 커밋 해시만이 확정 사실이다.

## 원인 (확정/미확정 구분)

- **미확정.** segfault의 정확한 원인은 규명되지 않았다.
- 확인된 상관관계: Cloud가 streamlit 1.59.1을 설치한 상태에서 segfault 발생,
  1.58.0으로 pin한 이후(및 기능 커밋 revert 이후) 정상.
- streamlit 1.59.x 자체의 결함인지, 특정 앱 코드와의 상호작용인지,
  다른 의존성과의 조합 문제인지는 확인되지 않았다.
- revert된 두 기능 커밋(`6369ae8`, `f4babe9`)과 segfault의 인과관계도
  확인된 바 없다.

## 낭비된 반복 대응 (재발 방지 사항)

이번 사건에서 확인된 낭비 패턴과 방지책:

1. **로그 미보존**: Reboot·재배포 과정에서 Cloud 로그를 저장하지 않아
   사후 원인 분석이 불가능해졌다.
   → 방지: 조치 전 로그 저장 최우선 (INCIDENT_PLAYBOOK.md §0)
2. **여러 변수 동시 변경**: 같은 날 pin push, 신규 기능 push, revert 2건이
   연달아 실행되어 어떤 조치가 효과를 냈는지 분리할 수 없게 되었다.
   → 방지: 단일 조치 원칙 (INCIDENT_PLAYBOOK.md §3)
3. **연쇄 revert**: 인과관계가 확인되지 않은 기능 커밋 2개를 revert했고,
   그 결과 정상 기능까지 운영에서 제거되었다.
   → 방지: revert는 원인으로 지목된 커밋 1개만 (DEPLOYMENT_GUARDRAILS.md)
4. **버전 미고정 상태의 자동 최신 설치**: `streamlit>=1.30`으로 인해
   로컬(1.58.0)과 Cloud(1.59.1)가 불일치했다.
   → 방지: 의존성 잠금 계획 (DEPENDENCY_LOCK_PLAN.md), 배포 전
   predeploy_check로 로컬 검증

## 남은 후속 작업 (별도 작업)

- streamlit 1.59.x segfault 원인 추적 및 업그레이드 재시도 (스테이징에서)
- revert된 기능(dashboard spacing, trade quote pairs)의 재적용 여부 결정
