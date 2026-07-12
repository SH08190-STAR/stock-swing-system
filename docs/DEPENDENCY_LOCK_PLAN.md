# DEPENDENCY_LOCK_PLAN — 의존성 잠금 계획

> 2026-07-12 segfault의 배경(로컬 1.58.0 vs Cloud 1.59.1 불일치) 재발 방지 계획.
> **이 문서는 계획만 기록한다. requirements.txt 변경은 스테이징 검증 전 금지.**

## 감사 결과 (2026-07-13, 로컬 py -3.12 환경 기준)

requirements.txt direct dependency vs 로컬 실제 설치 버전:

| 패키지 | requirements 스펙 | 로컬 설치 버전 | 비고 |
|---|---|---|---|
| pykrx | >=1.0.45 | 1.2.8 | 미고정 |
| finance-datareader | >=0.9.90 | 0.9.202 | 미고정 |
| pandas | >=2.0 | 2.3.3 | 미고정 |
| python-dateutil | >=2.8 | 2.9.0.post0 | 미고정 |
| supabase | >=2.0 | 2.31.0 | 미고정 |
| requests | >=2.31 | 2.34.2 | 미고정 |
| streamlit | ==1.58.0 | 1.58.0 | **유일한 pin** (2026-07-12 사건 대응) |
| python-dotenv | >=1.0 | 1.2.2 | 미고정 |
| openpyxl | >=3.1 | **로컬 미설치** | 코드에서 미사용 (README에만 언급) — 제거 후보 |
| pytest | >=8.0 | 9.1.1 | dev 전용 — runtime 분리 후보 |

- `pip check`: 로컬 환경 충돌 없음
- 위험: streamlit 외 9개가 범위 지정이라 Cloud 재배포 시점마다
  로컬과 다른(더 새로운) 버전이 설치될 수 있음 — 1.59.1 사건과 동일 구조

## Runtime / Dev 분리안

- `requirements.txt` (runtime — Streamlit Cloud가 설치):
  pykrx, finance-datareader, pandas, python-dateutil, supabase,
  requests, streamlit, python-dotenv
- `requirements-dev.txt` (로컬/CI 전용): `-r requirements.txt` + pytest
- openpyxl: 코드 사용처가 없으므로 분리 시점에 제거 검토
  (제거도 requirements 변경이므로 동일하게 스테이징 검증 필요)

## 단계별 잠금 계획

### 1단계 — 준비 (requirements 변경 없음)
- 로컬 정상 동작 버전 스냅샷 유지: `py -3.12 -m pip freeze > .tmp/pip_freeze.txt`
- 배포 전 `scripts/predeploy_check.py`로 설치 가능 여부·pip check 상시 확인

### 2단계 — 기능 브랜치에서 pin (일괄 아님, 이 순서로)
1. runtime/dev 분리 커밋 (버전 스펙은 그대로)
2. 위 표의 로컬 검증 버전으로 direct dependency `==` pin 커밋
3. 각 커밋마다 `predeploy_check.py` 통과 확인

### 3단계 — 스테이징 검증 후 반영
- 스테이징 앱(또는 별도 Cloud 앱)에 브랜치 배포
- `cloud_smoke_check.py --stability-minutes 10` 통과 확인
- 사용자 승인 후 main 반영 (DEPLOYMENT_GUARDRAILS.md 절차)

### 이후 운영 규칙
- 버전 업그레이드는 한 번에 한 패키지, 스테이징 검증 후
- streamlit 1.59.x 재시도는 별도 작업으로, 반드시 스테이징에서
  (참조: docs/incidents/2026-07-12-streamlit-segfault.md,
  [[streamlit-pin-158]] 메모: Cloud 검증 전 pin 해제 금지)

## 하지 않을 것

- 즉시 대량 pin push — 검증 없는 pin은 또 다른 단일 변경 원칙 위반
- `pip freeze` 전체를 requirements.txt로 덮어쓰기 — transitive까지 잠그면
  Cloud(Linux)와 로컬(Windows) 차이로 설치 실패 위험
