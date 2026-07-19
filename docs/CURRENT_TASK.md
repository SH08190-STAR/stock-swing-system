# CURRENT_TASK — 현재 활성 작업

> 이 문서는 **덮어쓰기** 문서다. 새 작업 시작 시 기존 내용을 누적하지 말고
> 아래 템플릿 전체를 새로 채운다. 작업이 없으면 상태를 `대기`로 둔다.

## 상태
대기  <!-- 대기 / 설계 / 구현 / 검수 / push 대기 / 완료 -->

## 직전 마일스톤 — 매매 카드 접힘 UX 운영 배포 **완료 (2026-07-19)**
- main = staging/ui-v3 = LKG = `25fab53` "feat: collapse trade record cards".
- release 직전 rollback tag `prod-pre-trade-card-collapse-20260719`(→`46f4d41`).
- 카드 접힘 Production 배포 완료, **사용자 운영 실화면 검증 정상**, 남은 블로커 없음.
- 전체 pytest 385 passed. GitHub pytest·deploy-smoke success.
  Production 4분 smoke 17회 실패 0(303→200). crash·traceback·segfault 0.
- 상세(카드 UX·인증 정책·롤백·인프라): docs/PROJECT_STATE.md
  "매매 카드 접힘 UX 운영" / "인증 정책" / "릴리스 tag" 섹션.

### 이번 릴리스에서 확정된 사항
- 매매기록 카드 기본 접힘 + 다중 펼침(UUID 기반 상태) + 개별 닫기 + 가격 갱신/수정
  저장 후 펼침·필터·로그인 유지. 모바일 검증 완료.
- **30일 로그인 제거** — Community Cloud proxy가 custom cookie를
  `st.context.cookies`로 전달하지 않아 서버 복원 불가. 현재 인증은
  APP_PASSWORD + st.session_state. APP_SESSION_SECRET 미사용.
- 후속 후보: Streamlit native OIDC 또는 자체 호스팅.

## 다음 목표 — 신규 작업 대기
후보(착수 전 사용자 승인 필요):
- **30일 로그인 재설계**: Streamlit native OIDC(st.login) 또는 자체 호스팅 검토.
- **KR Toss 지원 검증**: Toss KR 심볼 포맷 + `_resolve_symbol` 한글 종목명 처리.
- **거래대금 소스 전환**: pykrx/FDR 미제공 → data.go.kr 공공 API(키 발급 대기).
- 기타 대시보드·분류 로직 개선.

## DB write 허용 여부
아니오 (읽기 전용)

## push 허용 여부
문서 커밋만 허용(`docs: record trade card production release`). 기능 변경은 승인 후.
