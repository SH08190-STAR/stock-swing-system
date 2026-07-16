"""services/toss_relay 검증 — 실제 네트워크 호출 0회 (FastAPI TestClient + Fake).

fastapi/httpx가 없는 환경(기존 Streamlit CI)에서는 파일 전체가 skip된다.
아래 credentials/secret은 전부 형식만 흉내 낸 가짜 값이다(실제 발급값 아님)."""
import datetime as dt
import importlib
import socket
import sys
from decimal import Decimal

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app import toss as toss_mod  # noqa: E402
from services.toss_relay import main as relay_main  # noqa: E402
from services.toss_relay.config import (MIN_RELAY_SECRET_LEN, RelayConfig,  # noqa: E402
                                        RelayConfigError, load_config)

FAKE_RELAY_SECRET = "relay_FAKE_SHARED_SECRET_0123456789ABCD"   # 40자 가짜
FAKE_ID = "c_FAKE_CLIENT_ID_FOR_TEST"
FAKE_CLIENT_SECRET = "s_FAKE_CLIENT_SECRET_FOR_TEST"
FAKE_TOKEN = "FAKE.JWT.TOKEN_FOR_TEST"
SECRET_STRINGS = (FAKE_RELAY_SECRET, FAKE_ID, FAKE_CLIENT_SECRET, FAKE_TOKEN)

AUTH_OK = {"Authorization": f"Bearer {FAKE_RELAY_SECRET}"}
KST = dt.timezone(dt.timedelta(hours=9))
FULL_ENV = {"RELAY_SHARED_SECRET": FAKE_RELAY_SECRET,
            "TOSS_CLIENT_ID": FAKE_ID, "TOSS_CLIENT_SECRET": FAKE_CLIENT_SECRET}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """외부 socket 연결 차단 — 실제 네트워크 호출 0회 보증.
    (Windows asyncio가 내부 self-pipe로 쓰는 localhost socketpair만 허용)"""
    original_connect = socket.socket.connect

    def _guarded(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if host in ("127.0.0.1", "::1", "localhost"):
            return original_connect(self, address, *args, **kwargs)
        raise AssertionError("실제 외부 네트워크 호출 시도")

    monkeypatch.setattr(socket.socket, "connect", _guarded)


def price(symbol, value="183.42", currency="USD", ts=None):
    return toss_mod.TossPrice(
        symbol=symbol, last_price=Decimal(value), currency=currency,
        timestamp=ts or dt.datetime(2026, 7, 15, 10, 30, 0, tzinfo=KST))


class FakeTossClient:
    """app.toss.TossClient 대역 — get_prices 계약만 흉내."""

    def __init__(self, result=None, exc=None):
        self.calls = []
        self.result = result if result is not None else {}
        self.exc = exc

    def get_prices(self, symbols):
        self.calls.append(list(symbols))
        if self.exc is not None:
            raise self.exc
        return self.result


def make_client(*, fake=None, secret=FAKE_RELAY_SECRET, result=None, exc=None):
    """TestClient + fake TossClient + factory 호출 기록 생성."""
    fake = fake if fake is not None else FakeTossClient(result=result, exc=exc)
    created = []

    def factory(cfg):
        created.append(cfg)
        return fake

    cfg = RelayConfig(relay_shared_secret=secret, toss_client_id=FAKE_ID,
                      toss_client_secret=FAKE_CLIENT_SECRET)
    app = relay_main.create_app(config=cfg, toss_client_factory=factory)
    return TestClient(app), fake, created


# ── healthz ────────────────────────────────────────────────
def test_healthz_200():
    client, _, _ = make_client()
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_healthz_no_toss_call_and_no_token_issue():
    client, fake, created = make_client()
    for _ in range(5):
        assert client.get("/healthz").status_code == 200
    assert created == []            # TossClient 생성 0회 → 토큰 발급 0회
    assert fake.calls == []


def test_healthz_no_internal_details():
    client, _, _ = make_client()
    body = client.get("/healthz").text
    assert body == '{"status":"ok"}'
    for s in SECRET_STRINGS:
        assert s not in body


# ── 인증 ───────────────────────────────────────────────────
def test_missing_authorization_401():
    client, fake, _ = make_client()
    r = client.post("/v1/prices", json={"symbols": ["NVDA"]})
    assert r.status_code == 401
    assert r.json()["error"] == "UNAUTHORIZED"
    assert fake.calls == []


def test_wrong_bearer_401_same_generic_body():
    client, _, _ = make_client()
    no_header = client.post("/v1/prices", json={"symbols": ["NVDA"]})
    wrong = client.post("/v1/prices", json={"symbols": ["NVDA"]},
                        headers={"Authorization": "Bearer WRONG_TOKEN_x"})
    bad_scheme = client.post("/v1/prices", json={"symbols": ["NVDA"]},
                             headers={"Authorization": f"Basic {FAKE_RELAY_SECRET}"})
    assert wrong.status_code == bad_scheme.status_code == 401
    # 실패 사유와 무관하게 동일한 일반 401 본문
    assert no_header.json() == wrong.json() == bad_scheme.json()


def test_query_parameter_auth_rejected():
    client, fake, _ = make_client()
    r = client.post(f"/v1/prices?token={FAKE_RELAY_SECRET}",
                    json={"symbols": ["NVDA"]})
    assert r.status_code == 401
    assert fake.calls == []


def test_correct_token_success():
    client, fake, _ = make_client(result={"NVDA": price("NVDA")})
    r = client.post("/v1/prices", json={"symbols": ["NVDA"]}, headers=AUTH_OK)
    assert r.status_code == 200
    assert fake.calls == [["NVDA"]]


def test_constant_time_compare_used(monkeypatch):
    calls = []
    import hmac as _hmac

    def spy(a, b):
        calls.append(True)
        return _hmac.compare_digest(a, b)

    monkeypatch.setattr(relay_main, "_compare_digest", spy)
    client, _, _ = make_client(result={})
    assert client.post("/v1/prices", json={"symbols": ["NVDA"]},
                       headers=AUTH_OK).status_code == 200
    assert client.post("/v1/prices", json={"symbols": ["NVDA"]},
                       headers={"Authorization": "Bearer WRONG"}).status_code == 401
    assert len(calls) >= 2


# ── 설정 fail fast ─────────────────────────────────────────
def test_short_shared_secret_rejected():
    short = "S" * (MIN_RELAY_SECRET_LEN - 1)
    with pytest.raises(RelayConfigError):
        make_client(secret=short)
    with pytest.raises(RelayConfigError):
        load_config({**FULL_ENV, "RELAY_SHARED_SECRET": short})


@pytest.mark.parametrize("missing", ["RELAY_SHARED_SECRET", "TOSS_CLIENT_ID",
                                     "TOSS_CLIENT_SECRET"])
def test_missing_env_fails_startup(missing, monkeypatch):
    env = {k: v for k, v in FULL_ENV.items() if k != missing}
    with pytest.raises(RelayConfigError):
        load_config(env)
    # create_app() 무인자 경로도 동일하게 실패 (os.environ 기반)
    for k in FULL_ENV:
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(RelayConfigError):
        relay_main.create_app()


def test_config_repr_no_secret():
    cfg = RelayConfig(relay_shared_secret=FAKE_RELAY_SECRET,
                      toss_client_id=FAKE_ID, toss_client_secret=FAKE_CLIENT_SECRET)
    for s in SECRET_STRINGS:
        assert s not in repr(cfg)
        assert s not in str(cfg)


# ── 정상 응답 직렬화 ────────────────────────────────────────
def test_multi_price_response_shape():
    ts2 = dt.datetime(2026, 7, 15, 23, 59, 59, tzinfo=dt.timezone.utc)
    result = {"NVDA": price("NVDA", "183.42", "USD"),
              "NVDL": price("NVDL", "54.1050", "USD", ts=ts2)}
    client, _, _ = make_client(result=result)
    r = client.post("/v1/prices", json={"symbols": ["NVDA", "NVDL"]}, headers=AUTH_OK)
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "Toss"
    assert [p["symbol"] for p in body["prices"]] == ["NVDA", "NVDL"]
    # Decimal → 문자열 (정밀도 보존, float 변환 없음)
    assert body["prices"][0]["last_price"] == "183.42"
    assert body["prices"][1]["last_price"] == "54.1050"
    assert all(isinstance(p["last_price"], str) for p in body["prices"])
    # timezone-aware ISO 8601, 종목별 원본 timestamp 유지
    assert body["prices"][0]["timestamp"] == "2026-07-15T10:30:00+09:00"
    assert body["prices"][1]["timestamp"] == "2026-07-15T23:59:59+00:00"
    # 응답에 토큰·비밀값 없음
    for s in SECRET_STRINGS:
        assert s not in r.text


def test_missing_symbol_not_fabricated():
    client, _, _ = make_client(result={"NVDA": price("NVDA")})
    r = client.post("/v1/prices", json={"symbols": ["NVDA", "ZZZZ"]}, headers=AUTH_OK)
    assert r.status_code == 200
    assert [p["symbol"] for p in r.json()["prices"]] == ["NVDA"]


# ── 요청 검증 ──────────────────────────────────────────────
def _post(client, payload):
    return client.post("/v1/prices", json=payload, headers=AUTH_OK)


def test_200_symbols_allowed():
    client, fake, _ = make_client(result={})
    syms = [f"S{i:03d}" for i in range(200)]
    r = _post(client, {"symbols": syms})
    assert r.status_code == 200
    assert fake.calls == [syms]


@pytest.mark.parametrize("payload", [
    {"symbols": [f"S{i:03d}" for i in range(201)]},   # 201개
    {"symbols": []},                                  # 빈 배열
    {"symbols": ["NVDA", 123]},                       # 문자열 외 값
    {"symbols": "NVDA"},                              # 리스트 아님
    {"symbols": ["A" * 33]},                          # 과도한 길이
    {"symbols": ["   "]},                             # 빈 심볼
    {"symbols": [None]},
    {},                                               # symbols 누락
    ["NVDA"],                                         # dict 아님
])
def test_invalid_request_rejected(payload):
    client, fake, _ = make_client()
    r = _post(client, payload)
    assert r.status_code == 400
    assert r.json()["error"] == "INVALID_REQUEST"
    assert fake.calls == []


def test_max_symbol_length_boundary_ok():
    client, _, _ = make_client(result={})
    assert _post(client, {"symbols": ["A" * 32]}).status_code == 200


def test_arbitrary_upstream_url_not_forwardable():
    """extra 필드(url/endpoint/method 등)는 전부 거부 — 임의 상류 전달 불가."""
    client, fake, _ = make_client()
    for extra in ({"url": "https://evil.example"},
                  {"endpoint": "/api/v1/orders"},
                  {"method": "DELETE"},
                  {"path": "/oauth2/token"}):
        r = _post(client, {"symbols": ["NVDA"], **extra})
        assert r.status_code == 400
        assert r.json()["error"] == "INVALID_REQUEST"
    assert fake.calls == []


# ── 오류 매핑 ──────────────────────────────────────────────
@pytest.mark.parametrize("exc,status,code", [
    (toss_mod.TossAuthError(f"인증 실패 {FAKE_TOKEN}"), 503, "TOSS_AUTH_FAILED"),
    (toss_mod.TossForbiddenError("접근 거부 (403)"), 502, "TOSS_IP_FORBIDDEN"),
    (toss_mod.TossTimeoutError("timeout"), 504, "TOSS_TIMEOUT"),
    (toss_mod.TossResponseError("응답 형식 오류"), 502, "TOSS_BAD_RESPONSE"),
    (toss_mod.TossApiError(f"서버 오류 {FAKE_CLIENT_SECRET}"), 502,
     "TOSS_UPSTREAM_ERROR"),
    (RuntimeError(f"boom {FAKE_CLIENT_SECRET} {FAKE_TOKEN}"), 500, "INTERNAL_ERROR"),
])
def test_error_mapping_and_no_secret_leak(exc, status, code):
    client, _, _ = make_client(exc=exc)
    r = _post(client, {"symbols": ["NVDA"]})
    assert r.status_code == status
    body = r.json()
    assert body["error"] == code
    assert set(body) == {"error", "message"}
    # 예외 메시지·secret·token·stack trace 비노출
    for s in SECRET_STRINGS + ("boom", "Traceback", "RuntimeError"):
        assert s not in r.text


def test_rate_limit_with_retry_after():
    client, _, _ = make_client(
        exc=toss_mod.TossRateLimitError("한도 초과 (429)", retry_after=17))
    r = _post(client, {"symbols": ["NVDA"]})
    assert r.status_code == 429
    assert r.json()["error"] == "TOSS_RATE_LIMITED"
    assert r.headers["Retry-After"] == "17"


@pytest.mark.parametrize("retry_after", [None, -5, 10 ** 9])
def test_rate_limit_unsafe_retry_after_dropped(retry_after):
    client, _, _ = make_client(
        exc=toss_mod.TossRateLimitError("한도 초과 (429)", retry_after=retry_after))
    r = _post(client, {"symbols": ["NVDA"]})
    assert r.status_code == 429
    assert "Retry-After" not in r.headers


# ── 부분 반환(foundation per-item skip) 연동 ────────────────
def test_partial_result_three_of_four_returns_200():
    """TossClient가 4개 요청 중 3개만 돌려줘도(불량 item skip) Relay는 200 +
    정상 prices만 — 누락 심볼 placeholder 없음."""
    result = {"NVO": price("NVO", "51.21"), "TSLA": price("TSLA", "393.6"),
              "TSLL": price("TSLL", "12.18")}
    client, fake, _ = make_client(result=result)
    r = client.post("/v1/prices", headers=AUTH_OK,
                    json={"symbols": ["NVO", "NVOX", "TSLA", "TSLL"]})
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "Toss"
    assert [p["symbol"] for p in body["prices"]] == ["NVO", "TSLA", "TSLL"]
    assert "NVOX" not in r.text                     # placeholder/None/0 생성 없음
    assert fake.calls == [["NVO", "NVOX", "TSLA", "TSLL"]]


def test_empty_result_returns_200_empty_prices():
    """TossClient가 빈 dict를 반환하면(빈 result 정상 처리) 200 + 빈 prices."""
    client, _, _ = make_client(result={})
    r = client.post("/v1/prices", headers=AUTH_OK, json={"symbols": ["NVO"]})
    assert r.status_code == 200
    assert r.json() == {"provider": "Toss", "prices": []}


def test_all_invalid_items_still_maps_to_bad_response():
    """항목 전부 불량 → foundation TossResponseError → 502 TOSS_BAD_RESPONSE 유지."""
    client, _, _ = make_client(
        exc=toss_mod.TossResponseError("가격 응답 유효 항목 없음"))
    r = client.post("/v1/prices", headers=AUTH_OK, json={"symbols": ["NVO"]})
    assert r.status_code == 502
    assert r.json()["error"] == "TOSS_BAD_RESPONSE"
    for s in SECRET_STRINGS:
        assert s not in r.text


# ── singleton·lazy 생성 ────────────────────────────────────
def test_toss_client_singleton_reused():
    client, fake, created = make_client(result={})
    for _ in range(3):
        assert _post(client, {"symbols": ["NVDA"]}).status_code == 200
    assert len(created) == 1        # 프로세스(앱)당 1회만 생성
    assert len(fake.calls) == 3


def test_client_not_created_before_first_authorized_request():
    client, _, created = make_client()
    client.get("/healthz")
    client.post("/v1/prices", json={"symbols": ["NVDA"]})            # 401
    client.post("/v1/prices", json={"symbols": []}, headers=AUTH_OK)  # 400
    assert created == []            # 첫 "인증+유효" 요청 전에는 생성 없음


def test_import_no_network_no_client_creation(monkeypatch):
    """모듈 import만으로 네트워크·TossClient 생성이 없어야 한다."""
    def _boom(*args, **kwargs):
        raise AssertionError("import 중 TossClient 생성 시도")
    monkeypatch.setattr(toss_mod, "TossClient", _boom)
    monkeypatch.delitem(sys.modules, "services.toss_relay.main", raising=False)
    mod = importlib.import_module("services.toss_relay.main")
    assert hasattr(mod, "create_app")   # socket 차단(autouse) 아래에서 import 성공


# ── 표면 축소·응답 헤더 ────────────────────────────────────
@pytest.mark.parametrize("method,path", [
    ("GET", "/"), ("GET", "/docs"), ("GET", "/openapi.json"),
    ("GET", "/redoc"), ("POST", "/v1/orders"), ("GET", "/v1/accounts"),
    ("POST", "/oauth2/token"),
])
def test_unknown_endpoints_404(method, path):
    client, _, _ = make_client()
    assert client.request(method, path, headers=AUTH_OK).status_code == 404


def test_cache_control_no_store_everywhere():
    client, _, _ = make_client(result={})
    responses = [client.get("/healthz"),
                 _post(client, {"symbols": ["NVDA"]}),
                 client.post("/v1/prices", json={"symbols": ["NVDA"]}),  # 401
                 _post(client, {"symbols": []})]                          # 400
    for r in responses:
        assert r.headers.get("Cache-Control") == "no-store"
        assert r.headers.get("X-Relay-Api-Version") == "1"


def test_no_cors_headers():
    client, _, _ = make_client(result={})
    plain = client.get("/healthz", headers={"Origin": "https://example.com"})
    preflight = client.options(
        "/v1/prices",
        headers={"Origin": "https://example.com",
                 "Access-Control-Request-Method": "POST"})
    for r in (plain, preflight):
        assert "access-control-allow-origin" not in {k.lower() for k in r.headers}
    assert preflight.status_code in (404, 405)
