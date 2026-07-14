# CURRENT_TASK — 현재 활성 작업

> 이 문서는 **덮어쓰기** 문서다. 새 작업 시작 시 기존 내용을 누적하지 말고
> 아래 템플릿 전체를 새로 채운다. 작업이 없으면 상태를 `대기`로 둔다.

## 상태
완료  <!-- 대기 / 설계 / 구현 / 검수 / push 대기 / 완료 -->

## 완료 기록 (2026-07-14) — USD basis caption 표시 버그 수정 및 Streamlit Cloud 장애 대응
> 분류: UI/UX 단계 작업 아님(별도 버그 수정 + 운영 장애 대응). UI/UX 3단계(색상·간격·시각 디자인
> 개선)는 미착수 상태로 유지 — 아래 "다음 단계 후보" 참조.
- 미장 매매 카드 `_basis_caption`의 USD `$a … $b`가 st.caption(Markdown) LaTeX 수식으로
  렌더되던 문제를 반환 직전 `$`→`\$` escape 1줄로 해소(출력 문자열 전용).
- fix/us-basis-caption-dollar-rendering(`1e72627`) → main `--no-ff` 병합 `cd7f16c`, push 완료.
- tests·Deploy Smoke Check 성공(커밋 cd7f16c, smoke 371초).
- **운영 앱 실화면 확인 완료**(사용자, 2026-07-14): 미장 레버리지/본주 basis 달러 일반 텍스트·
  초록 수식/백슬래시 없음·상세 expander·국장 원화 카드·모바일 카드 압축 정상.
- LAST_KNOWN_GOOD_COMMIT을 `cd7f16c`로 승격(docs/PROJECT_STATE.md).
- DB write 없음. prices 58,371(레버리지 40/40 실조회 재검증)·trade_records 64·stocks 188·stock_targets 2 불변.

## 원인·수정 (참고)
- 원인: `_basis_caption`이 USD 레버리지에서 "본주 $1,915.92 · ETF $28.06"처럼 `$` 2개 포함 문자열 반환
  → st.caption(Markdown)이 `$...$` 구간을 LaTeX 인라인 수식(KaTeX)으로 렌더(초록 이탤릭). 국장(원화)은
  `$` 없음, 미장 본주 단독은 `$` 1개(쌍 불성립)라 미발생.
- 수정: 반환 직전 `.replace("$","\\$")` 1줄. 숫자 포맷·계산·저장값·다른 caption·모바일 CSS 무변경,
  unsafe_allow_html/HTML/CSS 미도입.
- 추가 테스트(tests/test_trades.py 4개): USD 레버리지 escape / USD 본주 단독 escape /
  KRW 문자열 완전 동일 / provider 없으면 None.

## 병합 전·후 검증 (참고)
- feature 커밋 1e72627 GitHub tests success 확인 후 병합.
- 병합 후: py_compile·전체 pytest 178 passed·git diff --check·predeploy(health 200 + 120초 생존) 통과.
- 독립 fresh 스테이징 2종(main control `kqf4sy24…`, basis-fix control-2=1e72627) 각 10분 smoke PASS(검사 29·실패 0).
- 로컬 UI 검수(390/1440px): 미장 basis 일반 텍스트(KaTeX 0·백슬래시 없음), 국장 원화 무변경, 모바일 압축 유지.

## 스테이징 인스턴스 Segmentation fault 사건 (해결)
- 병합 전 스테이징 `stock-swing-basis-fix-stagin`에서 최초 실행 + Reboot 1회 모두 segfault
  (PID 189→182), traceback·secret 오류 없음.
- 동일 commit/tree(1e72627, tree 3f0d1a9)를 별도 좌표에 fresh 배포한 두 독립 앱은 정상 →
  코드/의존성 원인 기각. 운영 앱은 hot update 후 PID 221 segfault → 전체 Reboot 후 fresh process
  정상(2026-07-14 10:24 UTC 새 프로세스), 10분 smoke PASS(검사 29·실패 0, 19:30~19:41 KST).
- working cause(추정, 근본 확정 아님): 장시간 실행 프로세스가 GitHub hot update 후 불안정 → segfault.
- 폐기 후보: basis-fix-stagin(장애 인스턴스) — 삭제 대상으로만 기록(이번 작업 미삭제).
- 상세: docs/PROJECT_STATE.md "스테이징 배포 인스턴스 Segmentation fault 사건·복구" 참조.

## 무변경 확인됨
- 매매 계산 로직·ETF quote-pair·수량 계산/반올림·FDR·DB/캐시·로그인 gate·모듈 reload guard·
  4개 내비게이션·모바일 카드 CSS(_MOBILE_CARD_CSS)·기존 함수명/시그니처/위젯 key·색상/뱃지,
  requirements/schema/CSV/workflow.

## 다음 단계 후보
- **UI/UX 3단계**: 색상·간격·시각 디자인 개선 (별도 승인·별도 브랜치, 계산/quote-pair/DB 로직 무변경).
- **운영 안정성(선택)**: 스테이징 segfault 근본 원인 미확정. 재발 시 fresh process 배포 좌표 분리
  A/B로 인스턴스 이상과 코드/의존성 문제를 구분하는 절차를 재사용.

## DB write 허용 여부
아니오 (읽기 전용 — DB write 없음)

## push 허용 여부
아니오 (문서 마감분 commit·push 전 — 사용자 승인 대기)
