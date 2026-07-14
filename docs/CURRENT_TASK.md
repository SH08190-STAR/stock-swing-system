# CURRENT_TASK — 현재 활성 작업

> 이 문서는 **덮어쓰기** 문서다. 새 작업 시작 시 기존 내용을 누적하지 말고
> 아래 템플릿 전체를 새로 채운다. 작업이 없으면 상태를 `대기`로 둔다.

## 상태
검수  <!-- 대기 / 설계 / 구현 / 검수 / push 대기 / 완료 -->

## 목표 — UI/UX 3단계 3C: 앱 헤더 + 요약 밴드 + 내비게이션 정돈
> 배경: 3B(색상 토큰·뱃지 팔레트) 운영 검증 완료(LKG=9bbd36d). 3A 전역
> config.toml 테마는 폐기 유지 — 3C도 .streamlit/config.toml·전역 CSS 없이
> **key 한정(st-key-*) CSS**만 사용한다.

- 브랜치: feature/ui-header-nav-v3c (기준 main=9bbd36d)
- 내용:
  1. 앱 헤더: 로그인 후 본문 최상단에 `app_header` container — 제목 "Z PICK" +
     보조 설명 "투자 유니버스 · 매매 계획 대시보드". 세로 여백 최소·이모지/그라데이션 없음.
  2. 요약 metric 밴드: 기존 metric 5개(값·라벨·순서·계산 유지)를 `summary_band`
     container로 감싸고, 그 범위 안에서만 흰 표면·1px 테두리·radius 10px·절제된
     padding·값/라벨 위계 CSS 적용. 모바일 압축용 max-width 640px 블록 포함.
  3. 상위 내비게이션: 기존 `top_nav` radio 유지, key 범위 CSS로 본문 구분선 +
     글자 굵기(600)·간격 정돈. radio 원형 유지(숨김 없음), pill 강제 없음.
  4. 하위 내비게이션: 기존 `sector_subnav`/`more_subnav` key 범위만, 상위보다
     한 단계 약한 위계(500/0.85rem). 필터·검색·시장·상태 radio 기능 무변경.
  5. 색상 토큰: `_C_SURFACE`, `_C_BORDER` 2종만 추가(3B 토큰 체계 연장).

## 이번 단계 제한 (3C) — 무변경(보호)
- 계산 로직·ETF quote-pair·수량 계산/반올림·FDR·DB·캐시·인증 gate·module reload guard.
- 4개 내비게이션 구조·기존 widget key·섹터/매매 카드 구조·상태/시장/2× 뱃지 매핑·
  로고 fallback 팔레트·모바일 카드 압축(_MOBILE_CARD_CSS)·use_container_width.
- requirements/schema/CSV/workflow 무변경. DB write 없음.
- 금지 selector: :has·nth-child·first/last-child·DOM 순서 의존·전역 stMetric·전역 CSS.

## 수정 허용 파일 (3C)
- dashboard/app.py
- docs/PROJECT_STATE.md
- docs/CURRENT_TASK.md

## 검증 계획
1. py_compile · 전체 pytest · git diff --check
2. 로컬 health 200 + 최소 120초 연속 실행, 서버 로그 traceback/AttributeError 없음
3. 모바일 390px / 데스크톱 1440px 실화면: 로그인 후 첫 화면·홈·섹터·매매·더보기·
   metric 5개·상하위 메뉴·사이드바·검색/필터/폼·섹터 카드·본주/레버리지 매매 카드·dataframe
4. 확인 항목: 제목/설명 과대 없음·모바일 첫 화면 길이 유지·metric 누락 없음·
   메뉴 rerun 상태 유지·상하위 위계 구분·카드 높이 무변화·가로 스크롤/겹침/잘림 없음·
   달러 basis 평문·기존 뱃지 색 유지

## 검증 결과 (로컬, 2026-07-15)
- py_compile OK, git diff --check OK, 전체 pytest **181 passed**(.tmp/pytest.log).
- 로컬 서버 health 200, 16분+ 연속 실행(>120초), 서버 로그 traceback·AttributeError 없음.
- 데스크톱 1440: 헤더(제목 20.8px/700·보조 13px 중립색, h1 없음, 높이 ~40px),
  summary_band metric 5개 흰 표면·1px #E5E7EB·radius 10px·padding 8.8/12.8px,
  값·라벨·순서 유지(62/34/0/92/2026-07-14). top_nav 하단 1px 구분선·15.2px/600,
  radio 원형 유지. 하위 subnav 13.6px/500(위계 구분). 홈/섹터/매매/더보기·사이드바
  필터·통합 검색(종목 1·매매기록 1)·dataframe 정상, 예외 0.
- 매매: 국장 11건·미장 카드 정상, 뱃지 실측 대기 #F1F5F9·2× #F5F3FF/#6D28D9 유지,
  USD basis "본주 $1,673.97 · ETF $21.00" 평문(KaTeX 0). 가격 새로고침 rerun 후
  매매/미장/대기중 선택 유지.
- 모바일 390: metric 5개 세로 스택·겹침/잘림/가로 스크롤 없음, 밴드 압축(값 20px·
  padding 6.4/10.4px). 섹터 카드 207px·metric 21.6px·padding 9.6/12px,
  매매 카드 624px — 3B 기준선과 동일(모바일 카드 압축 무변화).
- 참고: 로컬 APP_PASSWORD 미설정으로 gate 화면은 미표시(코드 무변경). 브라우저
  자동화의 스크린샷 캡처 기능 장애로 화면 검증은 computed style·geometry 실측으로 수행.

## DB write 허용 여부
아니오 (읽기 전용 — DB write 없음)

## push 허용 여부
아니오 (commit·push 금지 — 사용자 승인 대기)
