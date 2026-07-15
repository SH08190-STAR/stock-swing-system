# CURRENT_TASK — 현재 활성 작업

> 이 문서는 **덮어쓰기** 문서다. 새 작업 시작 시 기존 내용을 누적하지 말고
> 아래 템플릿 전체를 새로 채운다. 작업이 없으면 상태를 `대기`로 둔다.

## 상태
검수  <!-- 대기 / 설계 / 구현 / 검수 / push 대기 / 완료 -->

## 목표 — 토스증권 Open API 2차: 매매 화면 본주·ETF live overlay
> 배경: Toss foundation 1차(app/toss.py) 완료(main=3997bb6). 이번엔 매매 화면에서
> 본주·레버리지 ETF 현재가를 화면 표시용 live overlay로 반영한다. Supabase 최신
> 종가는 안정적 fallback·과거 데이터로 유지하고, DB에는 아무것도 쓰지 않는다.
> **이번 단계는 mock 기반 통합 + 로컬 검증까지만** — 실 credentials 입력·실호출·
> commit·push는 별도 승인 전 금지.

- 브랜치: feature/toss-live-overlay (기준 main=3997bb6)
- 내용:
  1. `app/config.py` — 선택 설정 `TOSS_CLIENT_ID`/`TOSS_CLIENT_SECRET`(env). 둘 다
     있을 때만 활성, 미설정은 정상(비활성). validate_for_collector·인증 gate 무영향.
  2. `app/toss_overlay.py` 신규 — Streamlit·DB·네트워크 비의존 순수 로직.
     `is_configured` / `collect_visible_symbols(records, resolve)` /
     `pick_single(overlay, sym)` / `pick_pair(overlay, base, etf, max_skew_sec=300)`.
     TossPrice→QuoteSnapshot 변환(Decimal·개별 timestamp 보존, provider="Toss").
     레버리지 쌍은 본주·ETF 둘 다 Toss + 유효 + 기준시각 차이 ≤5분일 때만 consistent,
     아니면 None(→DB 전체 fallback). 출처 혼합(본주 Toss+ETF DB) 원천 차단.
  3. `dashboard/app.py`:
     - `_toss_client()`(st.cache_resource — 프로세스당 client 1개, 토큰 내부 캐시,
       rerun마다 재발급 안 함), `toss_enabled()`.
     - `_fetch_toss_prices`(모든 Toss 예외 격리 → 빈 dict+타입명, 429 재시도 없음),
       `_toss_overlay_raw`(st.cache_data TTL 20초 — 20초 내 rerun은 재조회 안 함).
     - `_apply_toss_overlay(records)` — visible 기록 심볼만 1회 batch 조회 후
       session_state에 overlay 적재. 실패 시 매매 영역 안내 1회
       ("토스 실시간 시세를 사용할 수 없어 기존 가격을 표시합니다.").
     - `_trade_calc` 우선순위(한곳): 1) 수동 외부조회(_ext_quote) → 2) Toss →
       3) Supabase DB. 본주 단독도 동일(Toss→DB). base_as_of/etf_as_of 노출.
     - `clear_price_caches`에 `_toss_overlay_raw.clear()` 추가(가격 캐시만, 토큰 유지).
     - `_toss_skew_caption` — Toss 쌍일 때 본주·ETF 각 기준시각 표시.
  4. `tests/test_toss_overlay.py` 신규 — FakeTossClient·monkeypatch만, 실호출 0회. 31건.

## 우선순위 (코드 한곳 = _trade_calc)
1. 사용자가 버튼으로 조회한 수동 외부(FDR) 결과(_ext_quote) — 보존, Toss가 덮지 않음
2. Toss live overlay (provider="Toss")
3. Supabase DB 공통일자 pair / 최신 quote
4. 기존 FDR fallback (= 1의 수동 버튼 경로와 동일)

## 보안 정책 (절대)
- 실 credentials/access token/Authorization 헤더를 코드·테스트·로그·문서에 넣지 않음.
- Toss 예외 메시지는 고정 문구+상태코드만(toss.py 계약). 오류표식은 타입명만.
- 운영 앱만 credentials 상시 보유. 로컬·일반 스테이징은 mock. 단일 Client/token —
  운영·스테이징 동시 사용 금지(재발급 시 이전 토큰 무효).
- 이번 단계에서 실 credentials 입력·실호출·Streamlit Secrets 변경 없음.

## 이번 단계 제한 — 하지 않음
- Toss API 실호출, 실 credentials 입력, Streamlit Secrets 변경.
- commit·push, staging 이동, main 병합.
- DB write(prices/stocks/trade_records) — overlay는 메모리·cache·session_state만.

## 수정 허용 파일
- app/config.py
- app/toss_overlay.py (신규)
- dashboard/app.py
- tests/test_toss_overlay.py (신규)
- tests/test_trades.py (필요 시 최소 — 이번엔 변경 없음)
- docs/PROJECT_STATE.md, docs/CURRENT_TASK.md
- (app/toss.py는 foundation 계약 버그 시에만 — 이번엔 변경 없음)

## 보호 범위 — 무변경 확인
- ETF 2배 환산·수량/반올림·손절/필요자금·DB quote-pair v2 공통일자 로직·Supabase
  schema/data·일일 파이프라인·기존 FDR fallback·인증 gate·module reload guard·
  4개 내비게이션·UI/UX 3단계·모바일 카드 압축·requirements·schema·CSV·workflow.

## 검증 결과 (로컬, 2026-07-15)
- py_compile OK. tests/test_toss_overlay.py 31 passed(mock, 네트워크 0회).
  전체 pytest 241 passed(210 + 31). git diff --check clean.
- predeploy_check(--skip-tests): secret 패턴 PASS·compile PASS·requirements·pip check
  PASS·**Streamlit 서버 health 200, 120초 생존 PASS**. 서버 로그 오류·traceback 없음.
- credentials 미설정(.env에 TOSS 키 없음) 상태로 실행 — Toss 완전 비활성, 네트워크
  0회, 기존 매매/섹터 화면·가격·출처 이전과 동일(DB 경로).

## DB write 허용 여부
아니오 (읽기 전용 — overlay는 메모리/cache/session_state만)

## push 허용 여부
아니오 (commit·push 금지 — 실 credentials 입력 전 별도 승인 대기)
