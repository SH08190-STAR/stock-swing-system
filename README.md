# stock-swing-system

한국주식 워치리스트 단기스윙 자동 분류 시스템.
한국주식의 최근 6개월 일평균 거래대금이 1,000억 원 이하면 단기스윙으로 자동 분류하고,
웹 대시보드와 텔레그램으로 매 거래일 전달한다.

## 인수인계 문서 (먼저 읽기)
- PROJECT_SPEC.md — 확정 요구사항(단일 기준)
- ARCHITECTURE.md — 기술 스택/구성도
- DATA_MODEL.md — DB 스키마
- TASKS.md — 14단계 작업
- ACCEPTANCE_TESTS.md — 인수 테스트
- README_HANDOFF.md — 설치/배포/운영
- OPEN_DECISIONS.md — 미확정 선택지

## 빠른 시작
```bash
pip install -r requirements.txt
cp .env.example .env
pytest -q
python scripts/run_daily_update.py
streamlit run dashboard/app.py
```
배포 절차는 README_HANDOFF.md 참고.
