"""app/toss_relay_client.py 검증 — 실제 네트워크 호출 0회 (mock Session만 사용).

HTTP 계약(경로·body·헤더·timeout)·반환값·호출 횟수·오류 매핑을 검증한다.
requests 내부 구현에는 결합하지 않는다(Session.post 인터페이스만 흉내).
아래 token/URL은 형식만 흉내 낸 가짜 값이다(실제 발급값 아님)."""
import datetime as dt
from decimal import Decimal

import pytest
import requests

from app import toss_relay_client as rc
from app.toss_relay_client import (RelayPrice, TossRelayClient, TossRelayError,
                                   TossRelayAuthError, TossRelayRateLimitError,
                                   TossRelayTimeoutError, TossRelayUpstreamError,
                                   TossRelayResponseError)

FAKE_URL = "https://fake-relay.example.dev"
FAKE_TOKEN = "relay_FAKE_TOKEN_0123456789_ABCDEFGH"      # 36자 가짜
LEAK_STRINGS = (FAKE_TOKEN, "Authorization", "Bearer")


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
    """requests.Session 대역. 큐 항목이 Exception이면 raise, 아니면 반환."""

    def __init__(self, post_queue=None):
        self.post_queue = list(post_queue or [])
        self.post_calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.post_calls.append(
            {"url": url, "json": json, "headers": headers, "timeout": timeout})
        item = self.post_queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def item(symbol, price="183.42", currency="USD", ts="2026-07-16T02:35:20+09:00"):
    return {"symbol": symbol, "last_price": price, "currency": currency,
            "timestamp": ts}


def ok_resp(*items):
    return FakeResponse(200, {"provider": "Toss", "prices": list(items)})


def make(queue, **kw):
    session = FakeSession(post_queue=list(queue))
    client = TossRelayClient(FAKE_URL, FAKE_TOKEN, session=session, **kw)
    return client, session


# ── 1~4. 정상 응답·Decimal·timestamp 보존 ───────────────────
def test_success_two_symbols_decimal_and_timestamps():
    client, session = make([ok_resp(
        item("NVDA", "209.18", ts="2026-07-16T02:35:20+09:00"),
        item("NVDL", "32.3450", ts="2026-07-16T02:35:05+09:00"))])
    out = client.get_prices(["NVDA", "NVDL"])
    assert set(out) == {"NVDA", "NVDL"}
    assert isinstance(out["NVDA"], RelayPrice)
    assert out["NVDA"].last_price == Decimal("209.18")
    assert str(out["NVDL"].last_price) == "32.3450"          # 문자열 정밀도 보존
    assert out["NVDA"].currency == "USD"
    # timezone-aware + 종목별 원본 timestamp 유지(통일 금지)
    for p in out.values():
        assert p.timestamp.tzinfo is not None
        assert p.timestamp.tzinfo.utcoffset(p.timestamp) is not None
    assert out["NVDA"].timestamp != out["NVDL"].timestamp
    assert len(session.post_calls) == 1


# ── 5. 부분 누락 — 항목을 만들지 않음 ───────────────────────
def test_partial_missing_symbol_not_fabricated():
    client, _ = make([ok_resp(item("NVDA"))])
    out = client.get_prices(["NVDA", "ZZZZ"])
    assert list(out) == ["NVDA"]
    assert "ZZZZ" not in out


# ── 6. 중복 제거·대문자화·순서 유지 ─────────────────────────
def test_normalize_dedupe_upper_order():
    client, session = make([ok_resp(item("NVDA"), item("NVDL"))])
    client.get_prices([" nvda ", "NVDL", "NVDA", "", None, "nvdl"])
    assert session.post_calls[0]["json"] == {"symbols": ["NVDA", "NVDL"]}


# ── 7. 빈 배열 — HTTP 호출 없이 거부({} 반환) ────────────────
def test_empty_symbols_no_http_call():
    client, session = make([])
    assert client.get_prices([]) == {}
    assert client.get_prices(["", "  ", None]) == {}
    assert session.post_calls == []                          # Relay로 전송하지 않음


# ── 8. 201개 — 200개 단위 안전 chunk 분할 ───────────────────
def test_201_symbols_chunked_within_limit():
    syms = [f"S{i:03d}" for i in range(201)]
    client, session = make([ok_resp(), ok_resp()])
    client.get_prices(syms)
    assert len(session.post_calls) == 2
    assert len(session.post_calls[0]["json"]["symbols"]) == 200
    assert session.post_calls[1]["json"]["symbols"] == ["S200"]


# ── 9~10. URL 검증 ──────────────────────────────────────────
def test_https_only_and_trailing_slash_normalized():
    client, session = make([ok_resp()])
    assert repr(client) == f"TossRelayClient(base_url={FAKE_URL!r})"
    c2 = TossRelayClient(FAKE_URL + "/", FAKE_TOKEN, session=FakeSession([ok_resp()]))
    assert c2._base_url == FAKE_URL                          # trailing slash 정규화
    for bad in ("http://fake-relay.example.dev",             # http 거부
                "", None, "not-a-url"):
        with pytest.raises(TossRelayError):
            TossRelayClient(bad, FAKE_TOKEN, session=FakeSession())


def test_url_with_query_fragment_credentials_rejected():
    for bad in ("https://fake-relay.example.dev?x=1",
                "https://fake-relay.example.dev#frag",
                "https://user:pw@fake-relay.example.dev"):
        with pytest.raises(TossRelayError):
            TossRelayClient(bad, FAKE_TOKEN, session=FakeSession())


# ── 11. token 최소 길이 ─────────────────────────────────────
def test_token_min_length_and_empty_rejected():
    for bad in ("", None, "   ", "short_token", "x" * 31):
        with pytest.raises(TossRelayAuthError):
            TossRelayClient(FAKE_URL, bad, session=FakeSession())
    TossRelayClient(FAKE_URL, "x" * 32, session=FakeSession())   # 32자 경계 허용


# ── 12. Authorization Bearer 전달 계약 (query/body 금지) ────
def test_authorization_bearer_header_contract():
    client, session = make([ok_resp(item("NVDA"))])
    client.get_prices(["NVDA"])
    call = session.post_calls[0]
    assert call["url"] == FAKE_URL + "/v1/prices"            # endpoint 고정
    assert call["headers"]["Authorization"] == f"Bearer {FAKE_TOKEN}"
    assert FAKE_TOKEN not in call["url"]                     # query 전달 금지
    assert FAKE_TOKEN not in str(call["json"])               # body 전달 금지
    assert call["timeout"] == (3.0, 10.0)                    # connect 3s / read 10s


# ── 13~18. 오류 매핑 ────────────────────────────────────────
def test_http_401_maps_to_auth_error():
    client, session = make([FakeResponse(401, {"error": "UNAUTHORIZED",
                                               "message": "인증 실패"})])
    with pytest.raises(TossRelayAuthError):
        client.get_prices(["NVDA"])
    assert len(session.post_calls) == 1                      # 자동 재시도 없음


def test_http_429_with_retry_after():
    client, _ = make([FakeResponse(429, {"error": "TOSS_RATE_LIMITED",
                                         "message": "한도 초과"},
                                   headers={"Retry-After": "17"})])
    with pytest.raises(TossRelayRateLimitError) as ei:
        client.get_prices(["NVDA"])
    assert ei.value.retry_after == 17


@pytest.mark.parametrize("headers", [{}, {"Retry-After": "-3"},
                                     {"Retry-After": "abc"}])
def test_http_429_unsafe_retry_after_none(headers):
    client, _ = make([FakeResponse(429, {"error": "TOSS_RATE_LIMITED"},
                                   headers=headers)])
    with pytest.raises(TossRelayRateLimitError) as ei:
        client.get_prices(["NVDA"])
    assert ei.value.retry_after is None


@pytest.mark.parametrize("status,code", [
    (503, "TOSS_AUTH_FAILED"),
    (502, "TOSS_IP_FORBIDDEN"),
    (504, "TOSS_TIMEOUT"),
    (502, "TOSS_BAD_RESPONSE"),
    (502, "TOSS_UPSTREAM_ERROR"),
    (500, "INTERNAL_ERROR"),
])
def test_upstream_errors_keep_error_code(status, code):
    client, session = make([FakeResponse(status, {"error": code, "message": "오류"})])
    with pytest.raises(TossRelayUpstreamError) as ei:
        client.get_prices(["NVDA"])
    assert ei.value.error_code == code
    assert len(session.post_calls) == 1                      # 재시도 없음


def test_unexpected_5xx_without_json_body():
    client, _ = make([FakeResponse(502, None)])              # 본문 JSON 아님
    with pytest.raises(TossRelayUpstreamError) as ei:
        client.get_prices(["NVDA"])
    assert ei.value.error_code is None


def test_unexpected_4xx_generic_error():
    client, _ = make([FakeResponse(400, {"error": "INVALID_REQUEST"})])
    with pytest.raises(TossRelayError) as ei:
        client.get_prices(["NVDA"])
    assert not isinstance(ei.value, (TossRelayAuthError, TossRelayUpstreamError,
                                     TossRelayRateLimitError))


# ── 19~21. 응답 본문 이상 ───────────────────────────────────
def test_invalid_json_maps_to_response_error():
    client, _ = make([FakeResponse(200, None)])
    with pytest.raises(TossRelayResponseError):
        client.get_prices(["NVDA"])


@pytest.mark.parametrize("body", [
    {"provider": "NotToss", "prices": []},                   # provider 불일치
    {"prices": []},                                          # provider 누락
    {"provider": "Toss"},                                    # prices 누락
    {"provider": "Toss", "prices": "notalist"},
    ["provider", "Toss"],                                    # dict 아님
])
def test_bad_schema_or_provider_rejected(body):
    client, _ = make([FakeResponse(200, body)])
    with pytest.raises(TossRelayResponseError):
        client.get_prices(["NVDA"])


@pytest.mark.parametrize("bad_item", [
    item("NVDA", price="0"),                                 # 0 이하 가격
    item("NVDA", price="-1"),
    item("NVDA", price="NaN"),
    {"symbol": "NVDA", "last_price": 183.42,                 # 숫자(float) — 문자열 아님
     "currency": "USD", "timestamp": "2026-07-16T02:35:20+09:00"},
    item("NVDA", ts="2026-07-16T02:35:20"),                  # naive timestamp
    item("NVDA", ts="not-a-time"),
    {"last_price": "1", "currency": "USD",
     "timestamp": "2026-07-16T02:35:20+09:00"},              # symbol 누락
])
def test_bad_price_or_timestamp_rejected(bad_item):
    client, _ = make([ok_resp(bad_item)])
    with pytest.raises(TossRelayResponseError):
        client.get_prices(["NVDA"])


# ── 22. timeout / 네트워크 오류 ─────────────────────────────
def test_requests_timeout_maps_to_timeout_error():
    client, session = make([requests.Timeout("boom")])
    with pytest.raises(TossRelayTimeoutError):
        client.get_prices(["NVDA"])
    assert len(session.post_calls) == 1                      # 재시도 없음


def test_network_error_maps_to_relay_error():
    client, _ = make([requests.ConnectionError("down")])
    with pytest.raises(TossRelayError):
        client.get_prices(["NVDA"])


# ── 23. secret/token 비노출 ─────────────────────────────────
def test_no_token_in_repr_or_error_messages():
    client, _ = make([])
    for s in LEAK_STRINGS:
        assert s not in repr(client)
    cases = [FakeResponse(401, {"error": "UNAUTHORIZED"}),
             FakeResponse(429, {"error": "TOSS_RATE_LIMITED"}),
             FakeResponse(503, {"error": "TOSS_AUTH_FAILED"}),
             FakeResponse(200, None),
             requests.Timeout("t"), requests.ConnectionError("c")]
    for case in cases:
        c, _ = make([case])
        with pytest.raises(TossRelayError) as ei:
            c.get_prices(["NVDA"])
        assert FAKE_TOKEN not in str(ei.value)
        assert "Authorization" not in str(ei.value)


# ── 24~25. 재시도 0회·Session 재사용 ────────────────────────
def test_no_auto_retry_on_any_error():
    for err in (FakeResponse(503, {"error": "TOSS_AUTH_FAILED"}),
                FakeResponse(429, {"error": "TOSS_RATE_LIMITED"}),
                requests.Timeout("t")):
        client, session = make([err, ok_resp(item("NVDA"))])  # 두 번째 응답은 미소비
        with pytest.raises(TossRelayError):
            client.get_prices(["NVDA"])
        assert len(session.post_calls) == 1
        assert len(session.post_queue) == 1                   # 재호출 안 함


def test_session_reused_across_calls():
    client, session = make([ok_resp(item("NVDA")), ok_resp(item("NVDL"))])
    client.get_prices(["NVDA"])
    client.get_prices(["NVDL"])
    assert len(session.post_calls) == 2                       # 주입 session 그대로 재사용
