"""app/toss.py 검증 — 실제 네트워크 호출 0회 (mock Session만 사용).

HTTP 계약(경로·body·헤더·timeout)·반환값·호출 횟수를 검증한다.
requests 내부 구현에는 결합하지 않는다(Session.post/get 인터페이스만 흉내).
아래 credentials는 형식만 흉내 낸 가짜 값이다(실제 발급값 아님)."""
import datetime as dt
import threading
from decimal import Decimal

import pytest
import requests

from app import toss
from app.toss import (TossClient, TossPrice, TossApiError, TossAuthError,
                      TossForbiddenError, TossRateLimitError,
                      TossTimeoutError, TossResponseError)

FAKE_ID = "c_FAKE_CLIENT_ID_FOR_TEST"
FAKE_SECRET = "s_FAKE_CLIENT_SECRET_FOR_TEST"
FAKE_TOKEN = "FAKE.JWT.TOKEN_FOR_TEST"
FAKE_TOKEN2 = "FAKE.JWT.TOKEN_FOR_TEST_2"
SECRET_STRINGS = (FAKE_ID, FAKE_SECRET, FAKE_TOKEN, FAKE_TOKEN2, "Authorization")


# ── mock HTTP 계층 ──────────────────────────────────────────
class FakeResponse:
    def __init__(self, status_code=200, json_data=None, headers=None):
        self.status_code = status_code
        self._json = json_data
        self.headers = headers or {}

    def json(self):
        if self._json is None:
            raise ValueError("invalid json body")
        return self._json


class FakeSession:
    """requests.Session 대역. 큐의 항목이 Exception이면 raise, 아니면 반환."""

    def __init__(self, post_queue=None, get_queue=None):
        self.post_queue = list(post_queue or [])
        self.get_queue = list(get_queue or [])
        self.post_calls = []
        self.get_calls = []
        self._lock = threading.Lock()

    def post(self, url, data=None, headers=None, timeout=None):
        with self._lock:
            self.post_calls.append(
                {"url": url, "data": data, "headers": headers, "timeout": timeout})
            item = self.post_queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def get(self, url, params=None, headers=None, timeout=None):
        with self._lock:
            self.get_calls.append(
                {"url": url, "params": params, "headers": headers, "timeout": timeout})
            item = self.get_queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def token_resp(token=FAKE_TOKEN, expires_in=86400, token_type="Bearer", **over):
    body = {"access_token": token, "token_type": token_type, "expires_in": expires_in}
    body.update(over)
    for k, v in list(body.items()):
        if v is None:
            del body[k]
    return FakeResponse(200, body)


def price_item(symbol, price="100.0", currency="KRW", ts="2026-07-15T10:30:00+09:00"):
    return {"symbol": symbol, "lastPrice": price, "currency": currency, "timestamp": ts}


def prices_resp(*items):
    return FakeResponse(200, {"result": list(items)})


class Clock:
    """주입식 시계 — 만료 경계 테스트용."""

    def __init__(self, start=None):
        self.t = start or dt.datetime(2026, 7, 15, 1, 0, tzinfo=dt.timezone.utc)

    def now(self):
        return self.t

    def advance(self, seconds):
        self.t += dt.timedelta(seconds=seconds)


def make_client(session, **kw):
    return TossClient(FAKE_ID, FAKE_SECRET, session=session, **kw)


def assert_no_secret(exc):
    """예외 문자열·args 어디에도 credentials/token/Authorization 비노출."""
    texts = [str(exc), repr(exc)] + [str(a) for a in getattr(exc, "args", ())]
    if exc.__cause__ is not None:
        texts += [str(exc.__cause__), repr(exc.__cause__)]
    for t in texts:
        for s in SECRET_STRINGS:
            assert s not in t, f"예외에 비밀값 노출: {s}"


# ── 1~3. 토큰 발급·캐시·만료 ────────────────────────────────
def test_token_issue_contract():
    ses = FakeSession(post_queue=[token_resp()],
                      get_queue=[prices_resp(price_item("005930"))])
    out = make_client(ses).get_prices(["005930"])
    assert "005930" in out
    assert len(ses.post_calls) == 1
    call = ses.post_calls[0]
    assert call["url"].endswith("/oauth2/token")
    assert call["data"] == {"grant_type": "client_credentials",
                            "client_id": FAKE_ID, "client_secret": FAKE_SECRET}
    assert call["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert call["timeout"] == (3.0, 5.0)
    # 가격 요청은 Bearer 헤더 사용
    assert ses.get_calls[0]["headers"]["Authorization"] == f"Bearer {FAKE_TOKEN}"


def test_token_reused_before_expiry():
    ses = FakeSession(post_queue=[token_resp()],
                      get_queue=[prices_resp(price_item("005930")),
                                 prices_resp(price_item("005930"))])
    c = make_client(ses)
    c.get_prices(["005930"])
    c.get_prices(["005930"])
    assert len(ses.post_calls) == 1      # 만료 전 재사용 — 재발급 없음
    assert len(ses.get_calls) == 2


def test_token_reissued_within_5min_margin():
    clock = Clock()
    ses = FakeSession(post_queue=[token_resp(expires_in=600),
                                  token_resp(FAKE_TOKEN2, expires_in=600)],
                      get_queue=[prices_resp(price_item("005930")),
                                 prices_resp(price_item("005930"))])
    c = make_client(ses, now_fn=clock.now)
    c.get_prices(["005930"])
    clock.advance(301)                   # 남은 299초 < 5분 margin → 재발급
    c.get_prices(["005930"])
    assert len(ses.post_calls) == 2
    assert ses.get_calls[1]["headers"]["Authorization"] == f"Bearer {FAKE_TOKEN2}"


# ── 4~5. 401 처리 ───────────────────────────────────────────
def test_401_once_reissues_and_succeeds():
    ses = FakeSession(post_queue=[token_resp(), token_resp(FAKE_TOKEN2)],
                      get_queue=[FakeResponse(401),
                                 prices_resp(price_item("NVDA", "100.5", "USD"))])
    out = make_client(ses).get_prices(["NVDA"])
    assert out["NVDA"].last_price == Decimal("100.5")
    assert len(ses.post_calls) == 2      # 폐기 후 정확히 1회 재발급
    assert len(ses.get_calls) == 2       # 재요청 1회
    assert ses.get_calls[1]["headers"]["Authorization"] == f"Bearer {FAKE_TOKEN2}"


def test_repeated_401_raises_auth_error_no_third_try():
    ses = FakeSession(post_queue=[token_resp(), token_resp(FAKE_TOKEN2)],
                      get_queue=[FakeResponse(401), FakeResponse(401)])
    with pytest.raises(TossAuthError) as ei:
        make_client(ses).get_prices(["NVDA"])
    assert len(ses.get_calls) == 2       # 두 번째 401 후 추가 재시도 없음
    assert len(ses.post_calls) == 2
    assert_no_secret(ei.value)


# ── 6~9. 403 / 429 / timeout / 5xx ─────────────────────────
def test_403_forbidden():
    ses = FakeSession(post_queue=[token_resp()], get_queue=[FakeResponse(403)])
    with pytest.raises(TossForbiddenError) as ei:
        make_client(ses).get_prices(["005930"])
    assert_no_secret(ei.value)


def test_429_preserves_retry_after_and_no_auto_retry():
    ses = FakeSession(post_queue=[token_resp()],
                      get_queue=[FakeResponse(429, {}, {"Retry-After": "7"})])
    with pytest.raises(TossRateLimitError) as ei:
        make_client(ses).get_prices(["005930"])
    assert ei.value.retry_after == 7
    assert len(ses.get_calls) == 1       # 자동 sleep·재시도 없음
    # Retry-After 헤더가 없으면 None
    ses2 = FakeSession(post_queue=[token_resp()], get_queue=[FakeResponse(429, {})])
    with pytest.raises(TossRateLimitError) as ei2:
        make_client(ses2).get_prices(["005930"])
    assert ei2.value.retry_after is None


def test_timeouts_wrapped():
    # 토큰 발급 connect timeout
    ses = FakeSession(post_queue=[requests.exceptions.ConnectTimeout("boom")])
    with pytest.raises(TossTimeoutError) as ei:
        make_client(ses).get_prices(["005930"])
    assert ei.value.__cause__ is None    # 원본 예외 체인 차단(요청 정보 비노출)
    assert_no_secret(ei.value)
    # 가격 조회 read timeout
    ses2 = FakeSession(post_queue=[token_resp()],
                       get_queue=[requests.exceptions.ReadTimeout("boom")])
    with pytest.raises(TossTimeoutError):
        make_client(ses2).get_prices(["005930"])
    assert ses2.get_calls[0]["timeout"] == (3.0, 5.0)


def test_5xx_raises_base_api_error():
    ses = FakeSession(post_queue=[token_resp()], get_queue=[FakeResponse(503)])
    with pytest.raises(TossApiError) as ei:
        make_client(ses).get_prices(["005930"])
    assert type(ei.value) is TossApiError   # 하위 예외로 오분류하지 않음
    assert "503" in str(ei.value)


def test_prices_whole_request_404_no_partial_no_retry():
    """가격 조회 전체 요청 404 — 성공/부분 누락으로 처리하지 않고 예외.
    자동 재시도·토큰 재발급 없음. (경계조건 A)"""
    ses = FakeSession(post_queue=[token_resp()], get_queue=[FakeResponse(404, {})])
    with pytest.raises(TossApiError) as ei:
        make_client(ses).get_prices(["005930", "NVDA"])
    assert type(ei.value) is TossApiError   # 404를 Auth/Forbidden/RateLimit로 오분류 안 함
    assert "404" in str(ei.value)
    assert len(ses.get_calls) == 1          # 자동 재시도 없음
    assert len(ses.post_calls) == 1         # 토큰 재발급 없음
    assert_no_secret(ei.value)


# ── 10~12. 토큰 응답 이상 ───────────────────────────────────
def test_invalid_json_token_response():
    ses = FakeSession(post_queue=[FakeResponse(200, None)])   # json() → ValueError
    with pytest.raises(TossResponseError) as ei:
        make_client(ses).get_prices(["005930"])
    assert_no_secret(ei.value)


def test_missing_access_token():
    ses = FakeSession(post_queue=[token_resp(token=None)])
    with pytest.raises(TossResponseError):
        make_client(ses).get_prices(["005930"])


def test_bad_expires_in():
    for bad in (0, -10, "abc", None, True):
        ses = FakeSession(post_queue=[token_resp(expires_in=bad)])
        with pytest.raises(TossResponseError):
            make_client(ses).get_prices(["005930"])


# ── 13~19. 가격 batch 처리 ──────────────────────────────────
def test_price_batch_success():
    ses = FakeSession(post_queue=[token_resp()], get_queue=[prices_resp(
        price_item("005930", "79300", "KRW", "2026-07-15T15:30:00+09:00"),
        price_item("NVDA", "182.74", "USD", "2026-07-15T02:29:58.123+00:00"))])
    out = make_client(ses).get_prices(["005930", "NVDA"])
    assert set(out) == {"005930", "NVDA"}
    p = out["005930"]
    assert isinstance(p, TossPrice)
    assert p.last_price == Decimal("79300") and p.currency == "KRW"
    assert p.timestamp.tzinfo is not None
    assert ses.get_calls[0]["url"].endswith("/api/v1/prices")
    assert ses.get_calls[0]["params"] == {"symbols": "005930,NVDA"}


def test_per_symbol_timestamps_preserved():
    ses = FakeSession(post_queue=[token_resp()], get_queue=[prices_resp(
        price_item("005930", ts="2026-07-15T15:30:00+09:00"),
        price_item("46X910", ts="2026-07-15T15:29:41+09:00"))])
    out = make_client(ses).get_prices(["005930", "46X910"])
    a, b = out["005930"].timestamp, out["46X910"].timestamp
    assert a != b                        # batch라고 timestamp를 통일하지 않는다
    assert a.isoformat() == "2026-07-15T15:30:00+09:00"
    assert b.isoformat() == "2026-07-15T15:29:41+09:00"


def test_missing_symbol_not_in_result():
    ses = FakeSession(post_queue=[token_resp()],
                      get_queue=[prices_resp(price_item("005930"))])
    out = make_client(ses).get_prices(["005930", "UNKNOWN1"])
    assert "005930" in out and "UNKNOWN1" not in out
    assert len(out) == 1                 # 누락 심볼용 항목을 만들지 않는다


def test_symbol_dedupe_and_blank_removal():
    ses = FakeSession(post_queue=[token_resp()],
                      get_queue=[prices_resp(price_item("AAPL"), price_item("005930"))])
    out = make_client(ses).get_prices(["aapl", "AAPL", " ", "", None, "005930", "aapl"])
    assert ses.get_calls[0]["params"] == {"symbols": "AAPL,005930"}
    assert list(out) == ["AAPL", "005930"]     # 입력 순서 유지


def test_us_ticker_uppercased():
    ses = FakeSession(post_queue=[token_resp()],
                      get_queue=[prices_resp(price_item("NVDA"))])
    out = make_client(ses).get_prices(["nvda"])
    assert list(out) == ["NVDA"]
    assert ses.get_calls[0]["params"] == {"symbols": "NVDA"}


def test_chunking_over_200_symbols():
    syms = [f"S{i:04d}" for i in range(250)]
    resp1 = prices_resp(*[price_item(s) for s in syms[:200]])
    resp2 = prices_resp(*[price_item(s) for s in syms[200:]])
    ses = FakeSession(post_queue=[token_resp()], get_queue=[resp1, resp2])
    out = make_client(ses).get_prices(syms)
    assert len(ses.get_calls) == 2
    assert len(ses.get_calls[0]["params"]["symbols"].split(",")) == 200
    assert len(ses.get_calls[1]["params"]["symbols"].split(",")) == 50
    assert list(out) == syms             # chunk 병합 후에도 입력 순서 유지
    assert len(ses.post_calls) == 1      # 토큰은 1회 발급 재사용


def test_decimal_precision_preserved():
    ses = FakeSession(post_queue=[token_resp()],
                      get_queue=[prices_resp(price_item("NVDA", "195.7400", "USD"))])
    p = make_client(ses).get_prices(["NVDA"])["NVDA"].last_price
    assert isinstance(p, Decimal)
    assert p == Decimal("195.7400")
    assert str(p) == "195.7400"          # 문자열 원본 정밀도 보존(float 경유 없음)


# ── 20. 잘못된 가격·timestamp ───────────────────────────────
def test_timestamp_must_be_timezone_aware():
    """timezone offset·Z가 있는 timestamp는 정상 aware datetime으로 파싱. (경계조건 B)"""
    ses = FakeSession(post_queue=[token_resp()], get_queue=[prices_resp(
        price_item("005930", ts="2026-07-15T15:30:00+09:00"))])
    p = make_client(ses).get_prices(["005930"])["005930"]
    assert p.timestamp.tzinfo is not None
    assert p.timestamp.utcoffset() == dt.timedelta(hours=9)
    # Z(UTC) suffix도 aware로 인정
    ses_z = FakeSession(post_queue=[token_resp()], get_queue=[prices_resp(
        price_item("005930", ts="2026-07-15T06:30:00Z"))])
    pz = make_client(ses_z).get_prices(["005930"])["005930"]
    assert pz.timestamp.utcoffset() == dt.timedelta(0)


def test_naive_timestamp_rejected_not_assumed():
    """timezone 없는 naive timestamp는 TossResponseError — 로컬/UTC 임의 부여 금지. (경계조건 B)"""
    ses = FakeSession(post_queue=[token_resp()], get_queue=[prices_resp(
        price_item("005930", ts="2026-07-15T15:30:00"))])
    with pytest.raises(TossResponseError) as ei:
        make_client(ses).get_prices(["005930"])
    assert_no_secret(ei.value)


def test_bad_price_or_timestamp_raises_response_error():
    cases = [
        price_item("005930", price="abc"),
        price_item("005930", price="0"),
        price_item("005930", price="-5"),
        price_item("005930", price=None),
        price_item("005930", ts="not-a-date"),
        price_item("005930", ts="2026-07-15T15:30:00"),   # naive — timezone 없음
        {"lastPrice": "100", "currency": "KRW",
         "timestamp": "2026-07-15T15:30:00+09:00"},        # symbol 누락
    ]
    for item in cases:
        ses = FakeSession(post_queue=[token_resp()], get_queue=[prices_resp(item)])
        with pytest.raises(TossResponseError):
            make_client(ses).get_prices(["005930"])


# ── 20.5 부분 반환(per-item skip) — 불량 item이 batch를 오염시키지 않음 ──
BAD_ITEMS = [
    price_item("BAD1", price=None),                       # null 가격
    price_item("BAD1", price="0"),                        # 0 가격
    price_item("BAD1", price="-5"),                       # 음수 가격
    price_item("BAD1", price="abc"),                      # 비숫자 가격
    {"lastPrice": "100", "currency": "KRW",
     "timestamp": "2026-07-15T15:30:00+09:00"},           # symbol 누락
    {"symbol": "BAD1", "lastPrice": "100", "currency": "KRW"},  # timestamp 누락
    price_item("BAD1", ts="not-a-date"),                  # timestamp 파싱 불가
    price_item("BAD1", ts="2026-07-15T15:30:00"),         # naive timestamp
    "not-an-object",                                      # dict 아님
]


@pytest.mark.parametrize("bad", BAD_ITEMS)
def test_partial_one_valid_plus_one_bad_returns_valid_only(bad):
    """정상 1 + 불량 1 → 정상 1개만 반환(예외 없음). 불량 심볼은 dict에 없음
    (placeholder/None/0 생성 금지) — 호출측 pair 단위 DB fallback 계약 그대로."""
    ses = FakeSession(post_queue=[token_resp()], get_queue=[prices_resp(
        price_item("005930", "79300", "KRW", "2026-07-15T15:30:00+09:00"), bad)])
    out = make_client(ses).get_prices(["005930", "BAD1"])
    assert list(out) == ["005930"]
    assert "BAD1" not in out
    assert out["005930"].last_price == Decimal("79300")
    assert len(ses.get_calls) == 1        # 자동 재시도·심볼별 재호출 없음


def test_partial_two_valid_survive_one_bad():
    """정상 2 + 불량 1 → 정상 2개 전부 반환, Decimal·개별 timezone timestamp 보존."""
    ses = FakeSession(post_queue=[token_resp()], get_queue=[prices_resp(
        price_item("NVO", "51.21", "USD", "2026-07-16T16:57:19+09:00"),
        price_item("NVOX", price=None),                   # 데이터 지연 종목 흉내
        price_item("TSLA", "393.6000", "USD", "2026-07-16T16:57:38+09:00"))])
    out = make_client(ses).get_prices(["NVO", "NVOX", "TSLA"])
    assert list(out) == ["NVO", "TSLA"]   # 입력 순서 유지, NVOX 미포함
    assert str(out["TSLA"].last_price) == "393.6000"      # 문자열 정밀도 보존
    assert out["NVO"].timestamp.isoformat() == "2026-07-16T16:57:19+09:00"
    assert out["TSLA"].timestamp.isoformat() == "2026-07-16T16:57:38+09:00"
    assert out["NVO"].timestamp != out["TSLA"].timestamp  # 원본 개별 유지


def test_empty_items_returns_empty_dict():
    """빈 result 목록은 정상 빈 결과 — 예외 없음."""
    ses = FakeSession(post_queue=[token_resp()], get_queue=[prices_resp()])
    assert make_client(ses).get_prices(["005930"]) == {}


def test_all_items_invalid_raises_response_error():
    """항목이 있는데 전부 불량 → 전체 응답 손상으로 보고 TossResponseError
    (조용히 빈 결과로 숨기지 않음). 예외에 원본 item/body·secret 비노출."""
    ses = FakeSession(post_queue=[token_resp()], get_queue=[prices_resp(
        price_item("AAA", price=None), price_item("BBB", ts="not-a-date"))])
    with pytest.raises(TossResponseError) as ei:
        make_client(ses).get_prices(["AAA", "BBB"])
    assert_no_secret(ei.value)
    assert "not-a-date" not in str(ei.value)              # 원본 값 비포함
    assert "AAA" not in str(ei.value)


# ── 21. 비밀값 비노출 ───────────────────────────────────────
def test_no_secret_leak_in_any_exception_or_repr():
    scenarios = [
        FakeSession(post_queue=[FakeResponse(401)]),                       # 발급 401
        FakeSession(post_queue=[FakeResponse(200, None)]),                 # JSON 오류
        FakeSession(post_queue=[requests.exceptions.ConnectTimeout("x")]),
        FakeSession(post_queue=[token_resp()], get_queue=[FakeResponse(403)]),
        FakeSession(post_queue=[token_resp()],
                    get_queue=[FakeResponse(429, {}, {"Retry-After": "3"})]),
        FakeSession(post_queue=[token_resp()], get_queue=[FakeResponse(500)]),
        FakeSession(post_queue=[token_resp(), token_resp()],
                    get_queue=[FakeResponse(401), FakeResponse(401)]),
    ]
    for ses in scenarios:
        c = make_client(ses)
        with pytest.raises(TossApiError) as ei:
            c.get_prices(["005930"])
        assert_no_secret(ei.value)
        for s in SECRET_STRINGS:         # 클라이언트 repr에도 비노출
            assert s not in repr(c)


# ── 22. 동시 호출 시 토큰 중복 발급 방지 ─────────────────────
def test_concurrent_calls_issue_token_once():
    n = 8
    ses = FakeSession(post_queue=[token_resp()],
                      get_queue=[prices_resp(price_item("005930"))] * n)
    c = make_client(ses)
    barrier = threading.Barrier(n)
    errors = []

    def work():
        try:
            barrier.wait(timeout=5)
            out = c.get_prices(["005930"])
            assert "005930" in out
        except Exception as e:           # 스레드 안 실패를 본 스레드로 전달
            errors.append(e)

    threads = [threading.Thread(target=work) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert not errors
    assert len(ses.post_calls) == 1      # lock으로 토큰 발급 정확히 1회
    assert len(ses.get_calls) == n
