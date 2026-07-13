# CURRENT_TASK — 현재 활성 작업

> 이 문서는 **덮어쓰기** 문서다. 새 작업 시작 시 기존 내용을 누적하지 말고
> 아래 템플릿 전체를 새로 채운다. 작업이 없으면 상태를 `대기`로 둔다.

## 상태
완료  <!-- 대기 / 설계 / 구현 / 검수 / push 대기 / 완료 -->

## 완료 기록 (2026-07-14)
- UI/UX 1단계 — 상위 내비게이션 9개 탭 → 4개 메뉴(홈·섹터·매매·더보기) 재편.
- feature/ui-navigation-v2(`62724be`) → main `--no-ff` 병합 `43088fa`, push 완료.
- tests #30·deploy-smoke #7 성공, **운영 앱 실화면 확인 완료**(사용자, 2026-07-14):
  로그인·4개 메뉴 전환·기존 9개 기능·공통 metric/검색/사이드바 유지·매매 rerun 후 메뉴 유지·
  본주/ETF 카드·기준일 2026-07-10·환산값 정상, 빨간 오류·AttributeError·모듈 동기화 실패 없음.
- LAST_KNOWN_GOOD_COMMIT을 `43088fa`로 갱신(docs/PROJECT_STATE.md).
- DB write 없음. prices 58,371(레버리지 40/40 실조회 재검증)·trade_records 64·stocks 188·stock_targets 2 불변.

## 다음 단계 후보 (UI/UX)
- 2단계: 모바일 카드 압축 (카드 정보 밀도·세로 길이 최적화)
- 3단계: 색상·간격·시각 디자인 개선
- 착수 시 유의: 카드·CSS·색상·간격은 이번 1단계에서 의도적으로 무변경 유지했음.
  2·3단계는 별도 승인·별도 브랜치로 진행하고, 계산·quote-pair·DB 로직은 계속 무변경.

## (이전 작업 기록) UI/UX 1단계 상세 — 참고용
목표: 상위 내비게이션을 9개 탭에서 4개 상위 메뉴(홈·섹터·매매·더보기)로 재편.
기능 삭제 없이 기존 9개 화면을 하위 메뉴로 재배치. (기준 main=ad7906e, 병합 후 LKG=43088fa)

## 최종 메뉴 매핑
- 홈: 오늘 신규 편입 / 오늘 분류 이탈
- 섹터: 섹터 구성(기본) / 전체 종목 / 단기스윙
- 매매: 기존 매매 기록 기능 전체 그대로(render_trade_tab)
- 더보기: 거래대금 순위 / 변경 이력 / 확인 보류

## 구현 방식 (2026-07-13)
- `dashboard/app.py` main()에서 `st.tabs([...9...])`를 제거하고, key 지정
  horizontal `st.radio("메뉴", key="top_nav")` 상위 라우터로 교체.
- 섹터·더보기는 하위 `st.radio`(key="sector_subnav"/"more_subnav")로 화면 전환.
- 기존 탭 본문(전체/단기스윙/섹터 구성/신규 편입/분류 이탈/거래대금 순위/변경 이력/
  확인 보류/매매)은 **로직·문구·위젯 key·CSV 위치 변경 없이** 조건 분기 아래로 재배치만.
- 상단 요약 metric 5개·데이터 기준일·마지막 최신화·통합 검색·사이드바 필터는
  라우터 위에 그대로 두어 모든 메뉴 공통 노출.
- top_nav를 radio로 유지 → 매매 화면 st.rerun() 후에도 매매 메뉴 유지(기존 st.tabs는
  rerun 시 첫 탭 복귀 문제 있었음).

## 수정 허용 파일
- dashboard/app.py, docs/CURRENT_TASK.md

## 수정 금지 (무변경 확인됨)
- 계산 로직(_trade_calc·lev_convert·calc_position_qty·calc_total_pnl),
  ETF quote-pair(app/quotes.py·db_quote_pair·get_common_close_pair),
  FDR 조회, DB 로직, 캐시 함수, 로그인 gate, 모듈 reload guard,
  CSS·카드 디자인·색상·간격, requirements/schema/CSV/workflow.
- st.pills / :has / 복잡한 CSS selector 미사용.

## DB write 허용 여부
아니오 (읽기 전용 — DB write 없음)

## push 허용 여부
아니오 (로컬 검수 완료, 사용자 승인 대기)

## 검증 (2026-07-13)
- [x] py_compile (dashboard/app.py)
- [x] 전체 pytest 174 passed (.tmp/pytest.log)
- [x] git diff --check 통과 (dashboard/app.py 단일, +100/-92, 전부 main() 라우팅 영역)
- [x] 로컬 Streamlit(:8601) 실검수:
      로그인 통과, 4개 상위 메뉴 전환, 홈(신규 편입·분류 이탈)·섹터(섹터 구성 카드·
      전체·단기스윙)·매매(카드·환산가·기준일 2026-07-10·최신 가격 조회)·더보기(3화면)
      모두 도달, 공통 metric·검색·사이드바 전 메뉴 유지, 매매 '가격 새로고침'
      rerun(23:43→23:44) 후 매매 메뉴 유지, 콘솔·서버 traceback 없음.
