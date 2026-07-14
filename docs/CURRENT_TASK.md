# CURRENT_TASK — 현재 활성 작업

> 이 문서는 **덮어쓰기** 문서다. 새 작업 시작 시 기존 내용을 누적하지 말고
> 아래 템플릿 전체를 새로 채운다. 작업이 없으면 상태를 `대기`로 둔다.

## 상태
검수  <!-- 대기 / 설계 / 구현 / 검수 / push 대기 / 완료 -->

## 작업 (2026-07-14)
UI/UX 2단계 — 모바일 카드 밀도 개선.
섹터 종목 카드·매매 기록 카드의 모바일(≤640px) 세로 길이를 CSS만으로 압축.
브랜치 feature/mobile-card-density-v2 (기준 main=18f13b5, LKG=43088fa).

## 구현 방식
- Streamlit 1.58.0 `st.container(key=...)`가 컨테이너 노드에 `st-key-{key}` CSS
  클래스를 부여함을 로컬 DOM으로 확인(padding 15px·gap 16px이 이 노드에 직접 존재).
- 카드 컨테이너에 key 추가: `stock_card_{keyns}_{code}` / `trade_card_{record_id}`.
- `_MOBILE_CARD_CSS` 상수를 main()에서(gate 통과 후) 1회 주입.
  `@media (max-width: 640px)` + `[class*="st-key-stock_card_"]`/`[class*="st-key-trade_card_"]`
  속성 선택자만 사용 — :has·nth-child·전역 stMetric 선택자 없음.
- 압축 내용(카드 내부 한정): 컨테이너 padding 15px→0.6rem/0.75rem, 세로 gap 16px→0.4rem,
  metric value 36px→1.35rem·label 14px→0.75rem, caption line-height 1.6→1.3,
  카드 내 expander summary padding 4px→0.15rem.

## 수정 허용 파일
- dashboard/app.py, docs/CURRENT_TASK.md

## 수정 금지 (무변경 확인됨)
- 계산 로직(_trade_calc·lev_convert·calc_position_qty·calc_total_pnl),
  ETF quote-pair(app/quotes.py·db_quote_pair·get_common_close_pair),
  FDR 조회, DB 로직, 캐시 함수, 로그인 gate, 모듈 reload guard,
  4개 내비게이션 구조, 기존 함수명·시그니처·위젯 key,
  색상·뱃지·로고·그림자, requirements/schema/CSV/workflow.
- 상단 요약 metric 5개·사이드바·검색·입력 폼(새 기록/수정 expander 포함)은
  카드 key 밖이라 CSS 미적용(로컬 DOM으로 확인).
- st.pills / :has / 광범위 nth-child 미사용. metric 커스텀 HTML 재작성 없음.

## DB write 허용 여부
아니오 (읽기 전용 — DB write 없음)

## push 허용 여부
아니오 (commit·push 전 — 사용자 검수·승인 대기)

## 검증 (2026-07-14, 로컬 :8601)
- [x] py_compile (dashboard/app.py)
- [x] 전체 pytest 174 passed (.tmp/pytest.log)
- [x] git diff --check 통과 (dashboard/app.py 단일, +55/-2)
- [x] 모바일 390px 실측(접힌 카드 높이):
      섹터(삼성SDS) 285→207px(-27%), 매매 본주(108490) 885→624px(-30%),
      매매 레버리지(SNDK 2×SNXX) 822→587px(-29%). 가로 스크롤 없음(scrollWidth 390).
- [x] 데스크톱 1440px: 섹터 247px·매매 SNDK 416px — 변경 전과 동일(px 단위 일치),
      카드 padding 15px·gap 16px·metric 36px 유지. 상단 metric 36px·폼 expander padding 불변.
- [x] 매매 상세 expander 정상(환산가·출처·기준일·진입계획 표), 콘솔·서버 오류 없음.
- 참고: 상세 내 진입계획 st.dataframe 내부 요소는 자체 스크롤 영역(기존 동작, 변경 없음).
