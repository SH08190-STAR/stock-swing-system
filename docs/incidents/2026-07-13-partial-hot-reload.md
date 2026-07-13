# 2026-07-13 매매기록 탭 AttributeError (부분 hot-reload)

## 증상 (사실만)
- ETF quote-pair v2(main=bc2055a) 배포 후 운영 앱에서 매매기록 탭 진입 시 AttributeError.
- 호출 경로: render_trade_tab → _render_trade_card → _trade_calc → 가격 쌍/외부 캐시 구간.
- Cloud traceback: `app.database`에 `get_latest_quote` / `get_common_close_pair` 없음.
- 이전 2026-07-12 사건(Segmentation fault)과 다른 Python AttributeError.

## 환경 (버전·커밋)
- main = bc2055a (배포본). streamlit 1.58.0(Cloud pin) = 로컬 동일.
- 로컬 bc2055a에는 두 함수 모두 존재(hasattr True), 매매 40건 _trade_calc 오류 0/40.

## 타임라인 (조치·결과)
- 로그 확보 → 오류 분류 A(traceback). 로컬/스테이징 재현: 동일 커밋·동일 streamlit에서 재현 불가.
- 판정: 코드 누락이 아니라 **부분 hot-reload에 따른 모듈 버전 불일치**.
  Cloud가 dashboard/app.py만 새 버전으로 rerun하고 실행 중 프로세스의 app.database를 구버전으로 남김.
- 조치(코드, hotfix/cloud-module-reload-guard): 런타임 모듈 정합성 가드 추가.
  DB write·revert·Reboot 없음.

## 원인 (확정)
- **확정**: Streamlit Cloud 부분 hot-reload로 하위 모듈(app.database)이 구버전으로 잔존 →
  새 dashboard가 부르는 신규 함수 부재로 AttributeError. (로컬 동일 커밋 정상이 근거.)

## 재발 방지
- app/database.py·app/quotes.py에 `MODULE_API_VERSION` 명시.
- dashboard/app.py에 `check_and_recover_modules`: 필수 속성 + API 버전 계약 검사 →
  불일치 시 정확히 1회 `importlib.reload` 자동 복구, reload 발생 시에만 `st.cache_data.clear()`,
  복구 실패 시 traceback 대신 안내 문구 + `st.stop()`(내부 정보 비노출).
- db_quote_pair / db_single_quote 예외 격리(실패 계산만 보류, 서버 로그 1회 기록).
- 문서: INCIDENT_PLAYBOOK A-2, DEPLOYMENT_GUARDRAILS "부분 hot-reload 주의"
  (health 200이 하위 모듈 런타임 정합성을 보장하지 않음).
