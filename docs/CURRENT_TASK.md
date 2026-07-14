# CURRENT_TASK — 현재 활성 작업

> 이 문서는 **덮어쓰기** 문서다. 새 작업 시작 시 기존 내용을 누적하지 말고
> 아래 템플릿 전체를 새로 채운다. 작업이 없으면 상태를 `대기`로 둔다.

## 상태
검수  <!-- 대기 / 설계 / 구현 / 검수 / push 대기 / 완료 -->

## 목표 — UI/UX 3단계 3A: 라이트 테마 기반 확정
> 채택안: B "리서치 대시보드 톤"(균형형)을 4개 배포 단위(3A~3D)로 분리.
> 3A는 그 첫 단위로, **Streamlit 공식 theme 설정만** 도입한다(전역 테마 기반색).
> 상승/하락 규칙(확정): 상승=빨강+`+` 부호, 하락=파랑+`-` 부호(한국 관례). 3D에서 적용.

- 브랜치: feature/ui-theme-foundation-v3a (기준 main=ebe5d6d)
- `.streamlit/config.toml` 신규 — `[theme]` 5개 키만:
  - base=light, primaryColor=#2563EB, backgroundColor=#F8FAFC,
    secondaryBackgroundColor=#F1F5F9, textColor=#0F172A
- Streamlit 1.58.0 설치 버전에서 5개 키 모두 유효 확인(config._config_options).

## 이번 단계 제한 (3A)
- dashboard/app.py **수정 금지**(앱 제목·요약 밴드·내비 CSS·상태 뱃지·상승/하락 색·이모지·
  카드/버튼/expander 구조 전부 다음 단계로 미룸).
- 계산·ETF quote-pair·수량 계산·FDR·DB·캐시·로그인 gate·reload guard·내비게이션·
  모바일 카드 CSS(_MOBILE_CARD_CSS)·use_container_width 무변경.
- requirements/schema/CSV/workflow 무변경. DB write 없음. commit·push는 승인 후.

## 수정 허용 파일 (3A)
- .streamlit/config.toml (신규)
- docs/CURRENT_TASK.md

## 완료 기준 (3A)
- 전역 배경/보조배경/기본텍스트/primary가 목표 토큰과 일치, 대비·가독성 정상.
- 입력창·사이드바·dataframe가 배경에 묻히지 않음. 기존 카드 흰 배경·테두리·뱃지 대비 정상.
- 모바일 카드 압축 유지, 레이아웃·카드 높이 변화 없음, 기능/정보 누락·가로 스크롤 없음.
- 홈/섹터/매매/더보기 4개 화면 + 폼·상세 expander·dataframe·CSV 버튼 정상.

## 다음 단계 (미착수)
- 3B: 색상 토큰 상수화 + 상태 뱃지 시맨틱 통일 + 이모지 정리
- 3C: 앱 헤더 + 요약 밴드 CSS + 내비게이션 정돈(key-한정 CSS)
- 3D: 카드 정보 위계 + 경고 박스 + 손익/이격률 상승·하락 색(빨강/파랑 + 부호 병행)

## DB write 허용 여부
아니오 (읽기 전용 — DB write 없음)

## push 허용 여부
아니오 (사용자 승인 대기 — commit 전)
