# RUNBOOK — 장애 대응

1. 텔레그램 오류 알림에서 대상/원인/마지막 정상 시각 확인
2. GitHub Actions 최근 run 로그에서 실패 단계 확인
3. Supabase `errors` 테이블 최신 행 확인
4. 데이터 소스 장애: 다음 거래일 자동 재시도 / 급하면 workflow 수동 실행
5. 특정 종목만 hold: 신규상장·거래정지·코드변경 확인 → watchlist.csv 점검(임의 변경 금지, 사용자 승인 후)
6. 대시보드 미표시: Streamlit 로그 + Supabase 연결/Secrets 확인
7. 키 만료: 해당 플랫폼 Secrets 갱신
