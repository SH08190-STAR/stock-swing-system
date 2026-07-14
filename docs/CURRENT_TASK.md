# CURRENT_TASK — 현재 활성 작업

> 이 문서는 **덮어쓰기** 문서다. 새 작업 시작 시 기존 내용을 누적하지 말고
> 아래 템플릿 전체를 새로 채운다. 작업이 없으면 상태를 `대기`로 둔다.

## 상태
완료  <!-- 대기 / 설계 / 구현 / 검수 / push 대기 / 완료 -->

## 완료 기록 (2026-07-14) — UI/UX 2단계: 모바일 카드 밀도 개선
- 섹터 종목 카드·매매 기록 카드의 모바일(≤640px) 세로 길이를 CSS만으로 압축.
- feature/mobile-card-density-v2(`6aab986`) → main `--no-ff` 병합 `86333df`, push 완료.
- tests·Deploy Smoke Check 성공(커밋 86333df check-runs), 병합 전 스테이징 3분 Cloud smoke PASS
  (검사 12회·연속 실패 0·303→200).
- **운영 앱 실화면 확인 완료**(사용자, 2026-07-14): 모바일 섹터/본주/레버리지 카드 압축·상세 expander·
  가격/기준일/출처/환산값/수량 누락 없음·상단 metric/사이드바/검색/신규 기록 폼 정상·가로 스크롤/겹침/
  잘림 없음·데스크톱 레이아웃 정상, 빨간 오류·AttributeError·모듈 동기화 실패 없음.
- LAST_KNOWN_GOOD_COMMIT을 `86333df`로 갱신(docs/PROJECT_STATE.md).
- DB write 없음. prices 58,371(레버리지 40/40 실조회 재검증)·trade_records 64·stocks 188·stock_targets 2 불변.

## 구현 방식 (참고)
- Streamlit 1.58.0 `st.container(key=...)`가 컨테이너 노드에 `st-key-{key}` CSS 클래스를 부여함을
  로컬 DOM으로 확인. 카드 컨테이너에 key 추가: `stock_card_{keyns}_{code}` / `trade_card_{record_id}`.
- `_MOBILE_CARD_CSS` 상수를 main()에서(gate 통과 후) 1회 주입. `@media (max-width: 640px)` +
  `[class*="st-key-stock_card_"]`/`[class*="st-key-trade_card_"]` 속성 선택자만 사용 —
  :has·nth-child·전역 stMetric 선택자 없음.
- 압축(카드 내부 한정): 컨테이너 padding 15px→0.6/0.75rem, 세로 gap 16px→0.4rem,
  metric value 36px→1.35rem·label 14px→0.75rem, caption line-height→1.3, 카드 내 expander summary 축소.
- 카드 높이(모바일 390px, 접힘): 섹터 285→207px(-27%), 매매 본주 885→624px(-30%),
  매매 레버리지 822→587px(-29%). 데스크톱 1440px 카드 외형 무변경.

## 무변경 확인됨 (2단계에서 손대지 않음)
- 계산 로직(_trade_calc·lev_convert·calc_position_qty·calc_total_pnl),
  ETF quote-pair(app/quotes.py·db_quote_pair·get_common_close_pair),
  FDR 조회, DB 로직, 캐시 함수, 로그인 gate, 모듈 reload guard,
  4개 내비게이션 구조, 기존 함수명·시그니처·위젯 key,
  색상·뱃지·로고·그림자, requirements/schema/CSV/workflow.
- 상단 요약 metric 5개·사이드바·검색·입력 폼(새 기록/수정 expander 포함)은 카드 key 밖이라 CSS 미적용.

## 다음 단계 후보
- **UI/UX 3단계**: 색상·간격·시각 디자인 개선 (별도 승인·별도 브랜치, 계산/quote-pair/DB 로직 무변경 유지).
- **별도 버그**: 미장 basis caption의 `$...$` 수식 렌더링 문제
  (매매 카드 `_basis_caption` USD 표기가 Streamlit markdown LaTeX로 렌더 → 초록 이탤릭).
  2단계 범위 밖으로 미수정, docs/PROJECT_STATE.md "알려진 문제"에도 기록. 별도 브랜치로 처리.

## DB write 허용 여부
아니오 (읽기 전용 — DB write 없음)

## push 허용 여부
아니오 (문서 마감분 commit·push 전 — 사용자 승인 대기)
