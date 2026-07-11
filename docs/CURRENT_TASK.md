# CURRENT_TASK — 현재 활성 작업

> 이 문서는 **덮어쓰기** 문서다. 새 작업 시작 시 기존 내용을 누적하지 말고
> 아래 템플릿 전체를 새로 채운다. 작업이 없으면 상태를 `대기`로 둔다.

## 상태
push 대기  <!-- 대기 / 설계 / 구현 / 검수 / push 대기 -->
<!-- 구현 완료 2026-07-12: metric↔caption 간격 10px→1px, 전체 90 테스트 통과, health 200.
     로컬 UI 검수 완료 — push 승인됨 -->


## 목표
카드 내부의 작은 보조 텍스트(환산가, 52주 고점, 보조 라벨)의 세로 정렬/간격 보정

## 현상 또는 요청
- 매매 카드에서 "환산 $..." 같은 작은 글씨가 아래로 밀려 보임
- 섹터 카드에서 "52주 고점 ... · 고점 대비 ..." 줄이 현재가 블록 대비 너무 아래에 위치함
- 전반적으로 큰 숫자와 작은 회색 텍스트 사이 간격이 과함

## 완료 조건
- 카드 안의 보조 텍스트가 큰 숫자/메트릭 바로 아래에 자연스럽게 붙어 보일 것
- 카드 높이가 불필요하게 늘어나지 않을 것
- 모바일/PC 모두 가독성 개선
- 기능/데이터/계산/DB 경로 변화 없음

## 읽을 파일
- dashboard/app.py
- tests/test_dashboard.py

## 수정 허용 파일
- dashboard/app.py
- tests/test_dashboard.py

## 수정 금지 파일
- app/database.py
- scripts/run_daily_update.py
- scripts/schema.sql
- data/watchlist.csv
- watchlist.csv
- trade_records / stock_targets 데이터를 건드리는 모든 코드 경로
- .env

## DB write 허용 여부
아니오

## push 허용 여부
예 (커밋 메시지: feat: refine dashboard spacing)

## 관련 테스트 명령
- `py -3.12 -m py_compile dashboard/app.py`
- `py -3.12 -m pytest -q tests/test_dashboard.py`

## 전체 테스트 명령
`py -3.12 -m pytest -q > .tmp/pytest.log`

## 미해결 사항
- CSS 선택자가 Streamlit 버전에 과하게 의존하지 않게 구현할 것
- margin/padding/line-height만 최소 수정해서 해결할 것
