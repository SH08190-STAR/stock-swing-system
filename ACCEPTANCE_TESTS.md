# ACCEPTANCE_TESTS.md — 인수 테스트

모든 외부 데이터 소스는 mock으로 대체한다(네트워크 의존 금지, 가짜 금융데이터 생성 금지 — 합성값은 로직 검증 전용임을 코드에 명시).
임계값 상수: `SWING_THRESHOLD_KRW = 100_000_000_000` (1,000억).

각 항목은 `tests/` 아래 pytest로 구현하며, 전부 통과해야 완료(Done).

---

## A. 분류 정확성

### A1. 1,000억 미만 → swing
- 6개월 모든 거래일 거래대금 = 800억인 합성 일봉 → `classification == "swing"`.

### A2. 정확히 1,000억 → swing
- 평균이 정확히 100,000,000,000 → `"swing"` (이하 포함, 경계 부등호 검증).

### A3. 1,000억 초과 → sector
- 평균 1,500억 → `"sector"`.

### A4. 해외주식 분류 유지
- country != KR 종목은 거래대금 입력과 무관하게 분류 고정(미적용). M7도 동일.

## B. 무결성

### B1. 중복 분류 방지
- 임의 종목이 swing과 sector에 동시 존재하지 않음. 전체 종목의 classification은 단일값.

### B2. 동일 데이터 중복 저장 방지
- 같은 (code,date) 일봉을 2회 upsert해도 prices 행 수가 늘지 않음(멱등성).

### B3. 신규 편입 기록
- prev=sector, now=swing인 종목이 history에 (from=기존섹터, to=단기스윙)으로 1건 기록.

### B4. 기존 섹터 복귀 기록
- prev=swing, now=sector → history에 (from=단기스윙, to=기존섹터) 1건.

### B5. 변경 없음 시 미기록
- prev=now인 종목은 history에 추가되지 않음. 같은 날 재실행해도 중복 기록 없음.

## C. 예외/오류 처리

### C1. 휴장일 처리
- 거래일 판정이 '오늘은 비거래일'이면 수집을 스킵하고 status=skipped, 예외 없음.

### C2. 데이터 누락 처리
- 수집 결과 ohlcv=None(소스 전부 실패) → `classification=="hold"`, reason 기록, 예외 없음.

### C3. 거래정지(0원) 처리
- 6개월 중 일부 거래대금=0인 날은 평균에서 제외(used_days 감소), 평균 왜곡 없음.

### C4. 유효 거래일 부족(신규상장 의심)
- 유효 거래일 < 기준(예: 30) → `hold`, reason에 부족 표기.

### C5. 수집 실패 시 이전값 보존
- hold로 수치가 None일 때 save_classification이 avg_6m 등 기존값을 0/None으로 덮어쓰지 않음.

### C6. 데이터 소스 장애 전환
- pykrx가 예외/빈 결과 → FDR로 폴백해 수집 성공(근사면 estimated=True).

### C7. 텔레그램 전송 실패
- 전송 HTTP 실패 시 send()가 False 반환, 파이프라인은 계속 진행.

## D. 접근/표시

### D1. 인증 없는 외부 접근 차단
- APP_PASSWORD 설정 시, 미입력/오입력이면 대시보드 본문이 렌더되지 않음(게이트 통과 불가).

### D2. 모바일 화면
- 좁은 폭(예: 390px)에서 주요 표·메뉴가 가로 스크롤 또는 반응형으로 접근 가능(수동/스냅샷 확인 허용).

---

## 참조 구현 (검증 완료된 로직 — Claude Code가 tests로 이식)

```python
# tests/test_classifier.py 핵심 골격 (외부 소스 없이 동작)
import datetime as dt
import pandas as pd
from app import classifier as C
from app import config

END = dt.date(2026, 6, 19)
DATES = pd.bdate_range(END - pd.Timedelta(days=250), END)[-120:]

def _collected(value_per_day, close=10000, days=None):
    idx = DATES if days is None else DATES[-days:]
    df = pd.DataFrame({"close":[close]*len(idx), "volume":[1000]*len(idx),
                       "value":[value_per_day]*len(idx)}, index=idx)
    return {"code":"TEST","name":"T","market":"KOSPI","ohlcv":df,
            "status":"ok","reason":"","origin_sector":"x","origin_sub":"y","tier":"growth"}

def test_a1_below():   assert C.classify_one(_collected(800*10**8), END)["classification"]=="swing"
def test_a2_exact():   assert C.classify_one(_collected(1000*10**8), END)["classification"]=="swing"
def test_a3_above():   assert C.classify_one(_collected(1500*10**8), END)["classification"]=="sector"

def test_c3_halt_zero():
    c = _collected(800*10**8)
    c["ohlcv"].iloc[-5:, c["ohlcv"].columns.get_loc("value")] = 0
    assert C.classify_one(c, END)["used_days"] == 115

def test_c4_too_few():
    assert C.classify_one(_collected(500*10**8, days=20), END)["classification"]=="hold"

def test_c2_collect_fail():
    r = C.classify_one({"code":"X","name":"x","market":"KOSDAQ","ohlcv":None,
                        "status":"hold","reason":"blocked"}, END)
    assert r["classification"]=="hold"

def test_b3_b4_diff():
    prev={"A":"sector","B":"swing"}
    cur=[{"code":"A","classification":"swing","name":"A"},
         {"code":"B","classification":"sector","name":"B"}]
    d=C.diff_classifications(prev,cur)
    assert [x["code"] for x in d["new_swing"]]==["A"]
    assert [x["code"] for x in d["back_to_sector"]]==["B"]
```

> 위 골격은 이 대화에서 7개 케이스로 이미 통과 검증됨. Claude Code는 이를 출발점으로
> B1/B2/C1/C5/C6/C7/D1까지 mock 기반으로 확장한다.
