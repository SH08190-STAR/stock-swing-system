# CURRENT_TASK — 현재 활성 작업

> 이 문서는 **덮어쓰기** 문서다. 새 작업 시작 시 기존 내용을 누적하지 말고
> 아래 템플릿 전체를 새로 채운다. 작업이 없으면 상태를 `대기`로 둔다.

## 상태
검수  <!-- 대기 / 설계 / 구현 / 검수 / push 대기 / 완료 -->

## 목표 — UI/UX 3단계 3B: 색상 토큰 상수화 + 뱃지 팔레트 통일
> 배경: 3A(전역 config.toml 라이트 테마)는 스테이징에서 config만 차이 나는 상태로
> Segmentation fault 재현 → **폐기**. feature/ui-theme-foundation-v3a는 미병합 보관.
> 3B는 config.toml/전역 CSS 없이 **app.py 내부 인라인 색상만** 토큰화한다.
> Streamlit 기본 라이트 테마 유지. 상승/하락·손익 색은 3D로 미룸.

- 브랜치: feature/ui-color-tokens-v3b (기준 main=ebe5d6d)
- 내용:
  1. app.py 상단에 디자인 색상 토큰 상수 블록 신설(_C_TEXT_*, _C_LOGO_*, _BADGE_* 6종, _LOGO_FALLBACK_COLORS).
  2. 흩어져 있던 인라인 hex를 전부 이 토큰으로 치환(카드 헤더·매매 뱃지·로고 fallback).
  3. 상태 뱃지 팔레트 통일: 대기=중립 / 진입=파랑 / TP IN=앰버 / 완료=초록(_BADGE_STYLES가 토큰 참조).
  4. 시장(국장/미장)·본주=중립, 2× 레버리지=바이올렛으로 통일.
  5. 로고 fallback 8색 난립 → 안정적 4색(_LOGO_FALLBACK_COLORS)로 축소.
  6. 텍스트 라벨 전부 유지, 색만으로 상태 구분하지 않음.

## 이번 단계 제한 (3B) — 무변경
- 전역 배경·사이드바·입력창 테마(Streamlit 기본 라이트), .streamlit/config.toml 생성 금지, 전역 CSS 금지.
- 앱 헤더·요약 밴드·내비게이션 디자인(3C), 상승/하락·손익 색(3D), 이모지 정리, 카드 배경/테두리/그림자.
- 계산·ETF quote-pair·수량 계산·FDR·DB·캐시·로그인 gate·reload guard·내비게이션·
  모바일 카드 CSS(_MOBILE_CARD_CSS)·use_container_width·기존 함수명/시그니처/위젯 key.
- requirements/schema/CSV/workflow 무변경. DB write 없음.

## 수정 허용 파일 (3B)
- dashboard/app.py
- tests/test_trades.py (색상 매핑 회귀 테스트 추가)
- docs/CURRENT_TASK.md

## 추가 테스트 (색상 매핑 회귀, DOM/픽셀 미의존)
- test_badge_status_palette_mapping: 대기=중립/진입=파랑/TP IN=앰버/완료=초록(_BADGE_STYLES 토큰 매핑 + 색상 문자열).
- test_badge_market_type_and_leverage_mapping: 시장·본주=중립, 2×=바이올렛, 섹터=인디고, 5색 상호 구분.
- test_logo_fallback_palette_bounds: _LOGO_FALLBACK_COLORS 4색 고정 + 다양한 키에 _badge_color 반환이 항상 팔레트 내.

## 검증 결과 (로컬)
- py_compile OK, git diff --check OK, 전체 pytest **181 passed**(178+3, .tmp/pytest.log).
- 로컬 UI(데스크톱 1440 / 모바일 390, config 없음 → appBg 흰색 기본):
  - 상태 뱃지 실측: 대기 #F1F5F9, 진입 #DBEAFE, TP IN #FEF3C7, 완료 #DCFCE7. 라벨 텍스트 정상.
  - 시장 #F1F5F9, 본주 #F1F5F9, 2× 레버리지 #F5F3FF. 섹터 태그 #EEF2FF/#4338CA.
  - 로고 fallback 4색만 사용(#475569/#4F46E5/#0D9488/#B45309), 이미지 로고 병행.
  - 달러 basis 일반 텍스트 유지(KaTeX 0). 코드/날짜 보조색 #9CA3AF.
  - 홈/섹터/매매/더보기 정상, 모바일 카드 압축 유지(섹터 카드 높이 207px·metric 21.6px·padding 9.6/12px),
    가로 스크롤·예외·서버 traceback 없음.

## 다음 단계 (미착수)
- 3C: 앱 헤더 + 요약 밴드 + 내비게이션 정돈(전역 CSS 없이 key-한정 방식 재검토 — 3A segfault 교훈 반영).
- 3D: 카드 정보 위계 + 경고 박스 + 상승·하락·손익 색(상승 빨강+`+` / 하락 파랑+`-`, 텍스트 병행).

## DB write 허용 여부
아니오 (읽기 전용 — DB write 없음)

## push 허용 여부
아니오 (사용자 승인 대기 — commit 전)
