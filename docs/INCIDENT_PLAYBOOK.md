# INCIDENT_PLAYBOOK — 운영 장애 대응 절차

> 목적: 장애 시 반복 대응(무한 Reboot·연쇄 revert·추측성 수정)을 막고
> 로그 → 분류 → 재현 → 단일 조치 순서를 강제한다.

## 0. 최우선: 로그 확보 (조치보다 먼저)

어떤 조치(Reboot·revert·push)보다 **로그 저장이 먼저**다.
Reboot하면 Cloud 로그가 사라진다.

- Streamlit Cloud: Manage app → 로그 전문 복사
- 저장 위치: `.tmp/incident_<YYYY-MM-DD>_<n>.log` (로컬 임시)
- 사건 종료 후 사실 요약만 `docs/incidents/<YYYY-MM-DD>-<slug>.md`로 기록

## 1. 오류 분류 절차

로그에서 아래 순서로 판정한다. **분류가 끝나기 전에는 어떤 변경도 하지 않는다.**

| 유형 | 판정 근거 (로그) | 1차 대응 |
|---|---|---|
| A. Python traceback | `Traceback (most recent call last)` + 예외명·파일·라인 존재 | 해당 코드 경로를 로컬 재현 → 코드 수정 |
| B. Segmentation fault | traceback 없이 `Segmentation fault` / 프로세스 kill / oh no 화면 반복 | 앱 코드보다 **의존성·런타임 버전** 의심 → Cloud 설치 버전과 로컬 버전 비교 |
| C. dependency install 실패 | 배포 로그의 `pip install` 단계에서 에러 (resolver conflict, 빌드 실패) | requirements 최근 변경 확인 → 로컬 `pip install --dry-run -r requirements.txt` 재현 |
| D. Cloud 일시 장애 | 앱 로그에 오류 없음 + health만 실패 / Streamlit status 페이지에 incident / 여러 앱 동시 이상 | **아무것도 바꾸지 않고** 대기 → 15분 간격 재확인, Reboot 최대 1회 |

판정 팁:
- B는 로그 마지막 줄이 갑자기 끊기는 형태가 많다. 시작 후 사망까지의 시간을 기록한다.
- D를 A~C로 오판해 코드를 고치는 것이 최악의 낭비다. 먼저 https://status.streamlit.io 확인.
- **A-2 부분 hot-reload(모듈 버전 불일치)**: AttributeError인데 **누락됐다는 함수/속성이
  배포 커밋의 소스에는 분명히 존재**하면 코드 누락이 아니다. Streamlit Cloud가 여러 모듈이
  동시에 바뀐 배포에서 최상위 스크립트(dashboard/app.py)만 새로 rerun하고 하위 모듈
  (app.database 등)을 **구버전 프로세스에 남긴** 경우다. 판정 근거: 로컬 동일 커밋엔 함수 존재
  + Cloud만 AttributeError. 1차 대응: 앱에 내장된 런타임 모듈 가드가 1회 reload로 자동 복구하므로
  대개 rerun/재접속으로 해소된다. 해소 안 되면 Reboot 1회(D 준용). **revert 아님.**

## 2. 재현 순서 (수정 전 필수)

1. Cloud 로그에서 설치된 주요 버전(python, streamlit 등)을 기록
2. 로컬에서 동일 조건 재현 시도:
   - `py -3.12 scripts/predeploy_check.py` (health + 120초 생존 포함)
   - 버전 차이가 의심되면 **별도 venv**에 Cloud와 같은 버전을 설치해 재현
3. 로컬 재현 불가면 스테이징 앱에서 재현 (운영 앱으로 실험 금지)
4. 재현 성공 = 원인 후보 확정 → 3단계로. 재현 실패 = 분류로 돌아간다.

## 3. 단일 조치 원칙

- **한 번에 하나의 변수만 변경한다**: 코드 수정 / 의존성 pin / Reboot /
  revert 중 하나만 실행하고 결과를 확인한 뒤 다음을 판단한다.
- 조치 전 기록: 무엇을 왜 바꾸는지, 기대 결과 1줄
- 조치 후 기록: 실제 결과 (성공/실패/변화 없음)
- 같은 조치를 2회 반복하지 않는다 (Reboot 최대 1회 포함)
- 원인 확인 전 push·revert·Reboot 금지 — 예외는 D 유형의 Reboot 1회뿐

## 4. 로그·기록 형식

사건 문서 (`docs/incidents/<YYYY-MM-DD>-<slug>.md`):

```markdown
# <날짜> <제목>
## 증상 (사실만)
## 환경 (버전·커밋)
## 타임라인 (시각, 실행한 조치, 결과)
## 원인 (확정/미확정 구분 명시)
## 재발 방지
```

- 확정되지 않은 원인은 "추정"·"상관관계"로만 표기한다
- 로그 전문은 문서에 붙이지 않고 핵심 줄만 인용한다

## 5. 종료 조건

- health 200 + 10분 안정 (`scripts/cloud_smoke_check.py --stability-minutes 10`)
- 사건 문서 작성 완료
- 필요 시 docs/PROJECT_STATE.md의 LAST_KNOWN_GOOD_COMMIT 갱신
