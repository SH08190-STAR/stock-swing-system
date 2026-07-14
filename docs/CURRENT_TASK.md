# CURRENT_TASK — 현재 활성 작업

> 이 문서는 **덮어쓰기** 문서다. 새 작업 시작 시 기존 내용을 누적하지 말고
> 아래 템플릿 전체를 새로 채운다. 작업이 없으면 상태를 `대기`로 둔다.

## 상태
검수  <!-- 대기 / 설계 / 구현 / 검수 / push 대기 / 완료 -->

## 목표 — UI/UX 3단계 3D: 카드 정보 위계 · 경고 · 손익 표현
> 배경: 3C(헤더·요약 밴드·내비게이션) 운영 검증 완료(LKG=67ec9c9). 3A 전역
> config.toml 테마는 폐기 유지 — 3D도 .streamlit/config.toml·전역 CSS 없이
> **key 한정(st-key-*) CSS**와 인라인 style만 사용한다.

- 브랜치: feature/ui-card-hierarchy-v3d (기준 main=67ec9c9)
- 내용:
  1. 카드 표면 정돈: 섹터 카드(`stock_card_*`)·매매 카드(`trade_card_*`) key 범위에만
     흰 배경·1px `#E2E8F0` 테두리·radius 10px·절제된 그림자(`0 1px 2px rgba(15,23,42,.05)`).
     기존 카드 구조·열·위젯·정보·모바일 압축은 무변경.
  2. 상승/하락·손익 시맨틱색(한국 관례): 양수=빨강`#DC2626`+`+`, 음수=파랑`#2563EB`+`−`,
     0·없음=중립(부호 없음). **실제 등락·이격·손익 값에만** 적용:
     - 섹터 카드 52주 고점 대비 이격률(`_high_line_html`)
     - 섹터 카드 매매 연동 "현재가 대비" 이격률(`_trade_line_html`)
     - 매매 카드/상세 완료 **총 손익**(`_pnl_metric` — 부호별 container key로 metric 값 색)
     목표가·진입가·손절가 숫자 자체는 색칠하지 않는다. 순수 표현 helper 추가
     (`signed_pct_text`·`semantic_sign_color`·`signed_amount_text`·`_pnl_sign_key`) + 단위 테스트.
  3. 경고 영역: ETF 가격 쌍 불일치 경고를 회색 caption → 카드 내부 앰버 영역
     (배경 `#FEF3C7`·글자 `#92400E`·좌측 강조선 `#F59E0B`)으로. 문구 내용 무변경,
     정상 카드에는 렌더하지 않음(`_warn_box`).
  4. 보조 정보(basis·출처·기준일·환산·메모)는 보조 텍스트 위계 유지. USD basis `$` 평문
     유지(`_basis_caption` 무변경) — KaTeX 재발 없음.
  5. 색상 토큰: `_C_CARD_BORDER`·`_C_UP`·`_C_DOWN`·`_C_WARN_ACCENT` 추가(3B/3C 체계 연장).
     앰버 배경/글자는 `_BADGE_AMBER` 재사용, 카드 배경은 `_C_SURFACE` 재사용.

## 이번 단계 제한 (3D) — 무변경(보호)
- 계산 로직·ETF quote-pair·수량 계산/반올림·손절금액/필요자금·FDR·DB·캐시·인증 gate·
  module reload guard. **반올림·수식·기준값·데이터 소스 변경 없음**(표시만 변경).
- 4개 내비게이션 구조·기존 widget key·3B 뱃지 매핑·로고 fallback 팔레트·3C 헤더/metric/메뉴·
  `_MOBILE_CARD_CSS`·`_HEADER_NAV_CSS`·use_container_width.
- `format_52w_high_line`·`format_trade_line` 순수 함수 출력 무변경(test_dashboard.py 통과 유지) —
  렌더 사이트에서만 색 span으로 치환.
- requirements/schema/CSV/workflow 무변경. DB write 없음.
- 금지 selector: :has·nth-child·first/last-child·DOM 순서 의존·전역 stMetric·전역 CSS.

## 수정 허용 파일 (3D)
- dashboard/app.py
- tests/test_trades.py (순수 표현 helper 단위 테스트만)
- docs/PROJECT_STATE.md
- docs/CURRENT_TASK.md

## 카드 container key · CSS selector 전체 목록
- 기존 유지: `stock_card_*`, `trade_card_*`, `summary_band`, `top_nav`,
  `sector_subnav`, `more_subnav`, `app_header`.
- 신규(3D): `tr_pnl{pos|neg|flat}_{card|detail}_{id}` — 완료 총 손익 metric 부호별 색.
- 신규 CSS(`_CARD_V3D_CSS`, main()에서 1회 주입):
  - `[class*="st-key-stock_card_"], [class*="st-key-trade_card_"]` → 카드 표면(bg/border/radius/shadow)
  - `[class*="st-key-tr_pnlpos_"] [data-testid="stMetricValue"]` → `#DC2626`
  - `[class*="st-key-tr_pnlneg_"] [data-testid="stMetricValue"]` → `#2563EB`
  - `[class*="st-key-tr_pnlflat_"] [data-testid="stMetricValue"]` → 중립
- 경고 영역은 selector 미의존(인라인 style HTML `_warn_box`).

## 검증 결과 (로컬, 2026-07-15)
- py_compile OK, git diff --check OK, 전체 pytest **185 passed**(.tmp/pytest.log, 181+신규 4).
- 로컬 서버 health 200, 약 10분 연속 실행(>120초), 서버 오류·traceback 없음, 콘솔 오류 없음.
- 데스크톱 1440 실측(computed style·geometry — 스크린샷 캡처 장애로 대체 검증):
  - 카드 표면 62개(섹터)·매매 카드: bg `#FFFFFF`·border `1px #E2E8F0`·radius 10px·
    shadow `rgba(15,23,42,.05) 0 1px 2px`.
  - 섹터 52주 고점 대비 -51.0% → 파랑(37,99,235). 매매 연동 "현재가 대비" 이격률 색 적용.
  - 미장 완료 TEM 총 손익 양수 → 빨강(220,38,38, `tr_pnlpos`), 국장 완료 005930 총 손익
    "-146,123" → 파랑(37,99,235, `tr_pnlneg`) — 카드·상세 양쪽 슬롯 동일. 부호 중복 없음.
  - USD basis "본주 $58.23 · ETF $24.40" 평문(KaTeX 0). 2× 뱃지 바이올렛(245,243,255/109,40,217)
    23종 유지, 상태/시장/본주 뱃지 중립(#F1F5F9/#475569) 유지.
  - 정상(가격 쌍 일치) 카드에 경고 박스 없음(빈 영역 미렌더).
- 모바일 390 실측: 섹터 카드 207px·매매 레버리지 587px(3C 기준선과 일치), metric 21.6px(1.35rem)·
  padding 0.6/0.75rem, 완료 카드 pnl 래퍼도 모바일 압축 적용. 가로 스크롤·겹침·잘림 없음.
- 참고: 로컬 APP_PASSWORD 미설정으로 gate 화면 미표시(코드 무변경). ETF 가격 쌍 불일치
  경고는 현재 DB 데이터에 해당 레코드가 없어 라이브 미노출 — 코드 경로·문구는 보존.

## DB write 허용 여부
아니오 (읽기 전용 — DB write 없음)

## push 허용 여부
아니오 (commit·push 금지 — 사용자 승인 대기)
