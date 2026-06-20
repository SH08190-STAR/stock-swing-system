# README_HANDOFF.md — 인수인계 가이드

## 1. 프로젝트 설명

한국주식 워치리스트의 최근 6개월 일평균 거래대금을 매 거래일 자동 수집·계산해
**1,000억 원 이하면 단기스윙종목으로 자동 분류**하고, 결과를 웹 대시보드와 텔레그램으로 전달하는 무인 시스템.
완성 후 Claude 없이 독립 운영된다.

## 2. 개발환경 준비

- Python 3.11
- Git, GitHub 계정(비공개 저장소)
- 계정 3종: Supabase(무료), 텔레그램, Streamlit Community Cloud

## 3. 필요한 프로그램 / 라이브러리

`requirements.txt`: pykrx, finance-datareader, pandas, python-dateutil, supabase, requests, streamlit, python-dotenv, openpyxl, pytest

## 4. 환경변수 (.env.example → .env)

| 변수 | 용도 | 발급처 |
|---|---|---|
| SUPABASE_URL | DB 주소 | Supabase > Settings > API |
| SUPABASE_KEY | DB 키(쓰기 권한) | 동일 |
| TELEGRAM_BOT_TOKEN | 봇 토큰 | @BotFather |
| TELEGRAM_CHAT_ID | 수신 chat id | getUpdates |
| DASHBOARD_URL | 알림 내 링크 | Streamlit 배포 후 |
| APP_PASSWORD | 대시보드 비밀번호(선택) | 직접 지정 |
| NOTIFY_CHANNEL | telegram/discord/none | 기본 telegram |

`.env`는 커밋 금지(.gitignore 포함). 배포 시 각 플랫폼 Secrets에 동일 키 입력.

## 5. 실행 방법 (로컬)

```bash
pip install -r requirements.txt
cp .env.example .env          # 값 입력
python -m app.collector       # 종목 1개 수집 테스트
python scripts/run_daily_update.py   # 전체 1회 실행
streamlit run dashboard/app.py       # 대시보드 로컬
```

## 6. 테스트 방법

```bash
pytest -q                     # 전체
pytest tests/test_classifier.py -q   # 분류만
```
모든 외부 소스는 mock. 네트워크 없이 통과해야 한다.

## 7. 배포 방법

1. **Supabase**: 프로젝트 생성 → SQL Editor에 `scripts/schema.sql` 실행 → URL/Key 확보
2. **GitHub**: 비공개 저장소 push → Settings > Secrets에 환경변수 등록
3. **Streamlit Cloud**: 저장소 연결, main=`dashboard/app.py`, Secrets 입력 → URL 확보 → GitHub의 DASHBOARD_URL에 입력
4. **viewer allow-list**: Streamlit 앱 Sharing에서 허용 이메일 지정(비공개 유지)

## 8. 자동 실행 방법

`.github/workflows/daily-update.yml` — 평일 07:40 UTC(16:40 KST) 자동.
수동: Actions 탭 > daily-update > Run workflow.
휴장일은 스크립트가 거래일 판정 후 스스로 스킵.

## 9. 텔레그램 설정 방법

1. @BotFather → `/newbot` → 토큰 수령
2. 만든 봇과 대화창에서 메시지 1개 전송
3. `https://api.telegram.org/bot<토큰>/getUpdates` → `chat.id` 확인
4. 토큰·chat_id를 Secrets에 등록

## 10. 사용자가 직접 해야 하는 작업

- GitHub 비공개 저장소 생성 및 최초 push
- Supabase 프로젝트 생성 + schema.sql 실행
- 텔레그램 봇 생성 + chat_id 확보
- 각 플랫폼 Secrets 입력(키는 사용자만 보유)
- Streamlit 배포 및 viewer allow-list 지정
- 미확정 항목(아래 표)에서 결정 필요한 선택지 확정

## 11. Claude Code가 자동으로 할 작업

- 전체 코드 구현(collector/classifier/database/notifier/dashboard/scripts)
- 테스트 작성 및 통과
- 워크플로/스키마/문서 작성
- 단계별 Git 커밋
- 워치리스트 CSV 로딩(임의 변경 없이)

## 12. 데이터 소스 비교

| 소스 | 정확도 | 무료 | API키 | 호출제한 | 서버자동실행 | 안정성 | 약관 위험 | 장애 대체 |
|---|---|---|---|---|---|---|---|---|
| pykrx (주) | 높음(KRX 기반 실거래대금) | ✅ | 불필요 | 도의적 자제 권고 | ✅ | 높음(활발 유지보수) | 참고용, 상업적 사용 시 약관 준수 | FDR 폴백 |
| FinanceDataReader (예비) | 중(거래대금 일부 근사) | ✅ | 불필요 | 완만 | ✅ | 중상 | 스크래핑 기반, 참고용 | hold 처리 |
| KRX 공식/공공 API | 높음 | 일부 | 필요할 수 있음 | 기관별 상이 | ✅ | 높음 | 약관 확인 | 향후 1차 승격 검토 |

> 주 소스 차단·제한 시 자동 폴백. 근사값 섞이면 estimated=true 표시. 확인 불가 데이터는 생성하지 않음.

## 13. 장애 발생 시 확인 순서 (RUNBOOK 요약)

1. 텔레그램 오류 알림의 **오류 대상/원인/마지막 정상 시각** 확인
2. GitHub Actions 최근 run 로그 확인(실패 단계)
3. `errors` 테이블 최신 행 확인
4. 데이터 소스 장애면 다음 거래일 자동 재시도 대기 / 급하면 workflow 수동 실행
5. 특정 종목만 hold면 신규상장·거래정지·코드변경 여부 확인 후 watchlist.csv 점검(임의 변경 금지, 사용자 승인 후 수정)
6. 대시보드 미표시면 Streamlit 로그 + Supabase 연결/Secrets 확인
7. 키 만료면 해당 플랫폼 Secrets 갱신
