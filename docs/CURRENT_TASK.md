# CURRENT_TASK — 현재 활성 작업

> 이 문서는 **덮어쓰기** 문서다. 새 작업 시작 시 기존 내용을 누적하지 말고
> 아래 템플릿 전체를 새로 채운다. 작업이 없으면 상태를 `대기`로 둔다.

## 상태
검수  <!-- 대기 / 설계 / 구현 / 검수 / push 대기 / 완료 -->

## 작업 (2026-07-14)
미장 매매 카드 basis caption의 `$...$` 수식 렌더링 버그 수정.
브랜치 fix/us-basis-caption-dollar-rendering (기준 main=947ec5c, LKG=86333df).

## 원인
- `_basis_caption`(dashboard/app.py)이 USD 레버리지 카드에서
  "본주 $1,915.92 · ETF $28.06"처럼 `$` 2개를 포함한 문자열을 반환.
- 이를 `st.caption()`(Markdown)이 렌더하면서 `$...$` 구간을 LaTeX 인라인
  수식(KaTeX)으로 해석 → 초록/이탤릭 수식으로 표시.
- 렌더 위치: `_render_trade_card`·`_render_trade_detail`의 `st.caption(f"📊 {basis}")`.
- 국장(원화)은 `$` 없음, 미장 본주 단독은 `$` 1개(쌍 불성립)라 미발생.

## 수정 방식
- `_basis_caption` 반환 직전에 `$` → `\$` escape 1줄 추가(출력 문자열 전용).
- 숫자 포맷(`format_price`/`_fmtp`)·계산·저장값·다른 caption 무변경.
- unsafe_allow_html·HTML/CSS 도입 없음.

## 수정 허용 파일
- dashboard/app.py, tests/test_trades.py, docs/CURRENT_TASK.md

## 수정 금지 (무변경 확인됨)
- 매매 계산 로직·ETF quote-pair·수량 계산/반올림·FDR·DB/캐시·로그인 gate·
  모듈 reload guard·내비게이션·모바일 카드 CSS(_MOBILE_CARD_CSS)·
  requirements/schema/CSV/workflow.
- UI/UX 3단계 미착수.

## 추가 테스트 (tests/test_trades.py, 4개)
- test_basis_caption_usd_lev_escapes_dollar — 레버리지 USD: `\$` escape·unescaped `$` 없음
- test_basis_caption_usd_single_escapes_dollar — 본주 단독 USD 동일
- test_basis_caption_krw_unchanged — 원화 문자열 기존과 완전 동일
- test_basis_caption_none_without_provider — provider 없으면 None

## DB write 허용 여부
아니오 (읽기 전용 — DB write 없음)

## push 허용 여부
아니오 (commit·push 전 — 사용자 검수·승인 대기)

## 검증 (2026-07-14, 로컬 :8601)
- [x] py_compile (dashboard/app.py, tests/test_trades.py)
- [x] 전체 pytest 178 passed (기존 174 + 신규 4, .tmp/pytest.log)
- [x] git diff --check 통과 (dashboard/app.py +7/-2 · tests/test_trades.py +36)
- [x] 미장 레버리지(SNDK 2×SNXX)·본주 단독(OUST) 카드: basis가 일반 텍스트로 표시
      (KaTeX 요소 0, caption 색 단일 rgb(49,51,63), 백슬래시 화면 노출 없음),
      상세 expander 내 basis·환산값도 동일 정상. 기준일 2026-07-10·출처 Supabase 유지.
- [x] 국장(원화) basis 문자열 기존과 동일("본주 204,000원", KaTeX 0).
- [x] 모바일 390px: 카드 높이 587px(2단계 압축 유지)·padding 9.6/12px·gap 6.4px,
      가로 스크롤 없음. 데스크톱 1440px: 카드 416px·padding 15px(무변경).
- [x] 콘솔·서버 오류, traceback·AttributeError·모듈 동기화 실패 없음.
