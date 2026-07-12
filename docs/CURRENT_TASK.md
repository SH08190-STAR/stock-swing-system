# CURRENT_TASK — 현재 활성 작업

> 이 문서는 **덮어쓰기** 문서다. 새 작업 시작 시 기존 내용을 누적하지 말고
> 아래 템플릿 전체를 새로 채운다. 작업이 없으면 상태를 `대기`로 둔다.

## 상태
push 대기  <!-- 대기 / 설계 / 구현 / 검수 / push 대기 -->

## 목표
긴급 복구: 로컬(1.58.0)과 Streamlit Cloud(1.59.1)의 Streamlit 버전을
일치시켜 Cloud Segmentation fault를 해소한다.

## 현상 또는 요청
- Streamlit Cloud(1.59.1, Python 3.12.13)에서 앱 실행 약 2분 후 Segfault, traceback 없음
- 로컬(1.58.0)은 compile OK, 90 테스트 통과, health 200 정상
- requirements.txt의 `streamlit>=1.30` 미고정으로 Cloud가 1.59.1 설치 → 버전 불일치

## 조치
- requirements.txt: `streamlit>=1.30` → `streamlit==1.58.0` (로컬 실측 버전으로 pin)
- 다른 패키지·앱 코드·UI 코드 무변경
- use_container_width 경고 대응은 이번 범위 제외

## 완료 조건
- 새 venv에서 pin된 requirements 설치 성공
- `py -3.12 -m streamlit version` == 1.58.0
- py_compile OK, 전체 테스트 통과, 로컬 health 200
- main push (긴급 — 사용자 사전 승인됨)

## 수정 허용 파일
- requirements.txt
- docs/CURRENT_TASK.md

## 수정 금지 파일
- dashboard/app.py 및 모든 앱 코드
- DB·CSV·파이프라인·GitHub Actions
- .env

## DB write 허용 여부
아니오 (FORCE_RUN 금지)

## push 허용 여부
예 (긴급 복구 — 커밋 메시지: fix: pin Streamlit runtime version)

## 관련 테스트 명령
`py -3.12 -m pytest -q > .tmp/pytest.log`

## 미해결 사항
- Streamlit 1.59.x segfault 원인 추적 및 업그레이드 재시도는 별도 작업
- use_container_width deprecation 대응은 별도 작업
