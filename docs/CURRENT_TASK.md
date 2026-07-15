# CURRENT_TASK — 현재 활성 작업

> 이 문서는 **덮어쓰기** 문서다. 새 작업 시작 시 기존 내용을 누적하지 말고
> 아래 템플릿 전체를 새로 채운다. 작업이 없으면 상태를 `대기`로 둔다.

## 상태
검수  <!-- 대기 / 설계 / 구현 / 검수 / push 대기 / 완료 -->

## 목표 — Toss live overlay fix 1 (비활성 경로 완전 우회)
> 배경: staging(0161184)에서 로그인→매매→미장→TP IN 시 segfault 재현,
> revert(59144b1) 후 동일 동작 정상 — overlay commit과 crash의 상관성 확인
> (원인 라인 미확정). fix 1은 **credentials 미설정 시 Toss runtime 경로를
> 완전히 우회**해 3997bb6 실행 경로와 동일하게 만드는 최소 변경이다.
> 0161184 전체 재배포·main 병합 금지 유지.

- 브랜치: feature/toss-live-overlay-fix1 (기준 staging/ui-v3=59144b1,
  `git cherry-pick -n 0161184` 후 fix 반영 — commit 전)
- Fix 1 변경(0161184 대비, dashboard/app.py만):
  1. **게이트 단일화**: `_maybe_apply_toss_overlay(records)` 신설 —
     `toss_enabled()`(순수 문자열 검사, cache·client·import 미접근)가 False면
     False만 반환. `_apply_toss_overlay`·심볼 수집·cache 접근·session_state
     생성 전부 미실행. render_trade_tab은 이 게이트만 호출.
  2. **None cache 금지**: credentials 검사를 cache_resource 밖(toss_enabled)으로
     이동. `_toss_client()`는 항상 유효한 TossClient만 반환(게이트 뒤 전용,
     잘못 호출되면 TossAuthError — 예외는 캐시 안 됨). 비활성 시 호출 0회.
  3. **lazy import**: dashboard 상단 `from app import toss` 제거 —
     `_toss_client`(TossClient)·`_fetch_toss_prices`(예외 타입)에서만 lazy import.
     비활성 프로세스에 app.toss(→requests) 로드 0. `app/toss_overlay.py`는
     원래 app.quotes만 의존(무변경).
  4. **session_state 최소화**: 비활성 시 Toss key 생성·빈 dict 재할당 없음
     (key 부재 → `_toss_overlay_state()`={}). `_ext_quote` 무변경.
  5. **_trade_calc 비용 최소화**: `_toss_pair`/`_toss_single` 제거, rerun당
     `ov = _toss_overlay_state()` 1회 → `ov`가 비면 기존 `_ext_quote → DB`
     경로 그대로(카드별 tov helper 호출 0). 활성 우선순위 유지:
     수동 _ext_quote → Toss → DB → (수동 버튼 FDR).

## 테스트 (tests/test_toss_overlay.py — 38건)
- 기존 31건 계약 유지(활성 경로: client 재사용·batch 20초·skew 5분·한쪽 누락
  fallback·수동 우선·혼합 금지·secret 비노출 등).
- 신규 7건(비활성): 게이트가 client/raw/apply/수집/info 호출 0회(둘 다·한쪽
  credential 없음 parametrize, 필터 3회 변경 포함)·Toss session key 생성 0·기존
  key 무변경·_trade_calc가 tov helper 호출 없이 DB 경로와 동일 결과·
  **dashboard 로드+비활성 실행이 app.toss import 불요(sys.modules 검증)**·
  활성 게이트 1회 호출·None 미캐시(빈 creds 호출 시 예외).

## 보호 범위 — 무변경
- app/toss.py(foundation)·dashboard/database.py·ETF 2배 공식·수량/반올림·
  DB quote-pair v2·FDR 경로·인증 gate·UI/UX·requirements·dependency 버전·
  schema/CSV/workflow·DB 데이터. use_container_width 미수정.

## 이번 단계 제한 — 하지 않음
- 실 credentials 입력·Secrets 변경·Toss 실호출·main 병합·staging 이동·
  commit·push·Reboot·DB write.

## 검증 결과 (로컬, 2026-07-15)
- py_compile OK. test_toss.py 25 + test_toss_overlay.py 38 passed(실호출 0회).
- 전체 pytest 248 passed(.tmp/pytest.log). git diff --check clean.
- credentials 미설정 로컬 앱: health 200·120초 생존(predeploy_check), 로그
  오류·traceback 없음, app.toss 미로드.

## DB write 허용 여부
아니오 (읽기 전용)

## push 허용 여부
아니오 (commit·push 금지 — 사용자 승인 대기)
