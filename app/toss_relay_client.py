"""toss_relay_client.py — Toss 시세 Relay(Fly.io) HTTP 클라이언트 (순수 모듈, Streamlit 비의존).

Streamlit → Relay HTTPS → Toss 구조에서 Streamlit 쪽이 쓰는 클라이언트다.
Toss credentials·OAuth token은 Relay 서버에만 존재하며 이 모듈은 다루지 않는다.
이 모듈은 어디에도 print/log를 남기지 않으며, 어떤 예외 문자열에도 relay token·
Authorization 헤더·URL query·응답 원본 body를 포함하지 않는다(고정 한글 메시지 +
HTTP 상태코드만). app/toss.py(TossClient)는 Relay 서버 내부 전용 — 여기서 import하지
않는다(대시보드 프로세스에 불필요한 로드 방지).

Relay 계약(services/toss_relay/main.py):
- POST {base_url}/v1/prices, Authorization: Bearer <RELAY_SHARED_SECRET>
- 요청 {"symbols": [...]} 최대 200개 — 초과분은 200개 단위 chunk로 분할
- 성공 {"provider":"Toss","prices":[{symbol,last_price(문자열),currency,timestamp(ISO)}]}
- 오류 {"error": code, "message": ...} — 401/429/502/503/504
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

import requests

PRICES_PATH = "/v1/prices"
CONNECT_TIMEOUT_SEC = 3.0
READ_TIMEOUT_SEC = 10.0
MAX_SYMBOLS_PER_REQUEST = 200       # Relay /v1/prices 상한(서버 계약과 동일)
MIN_TOKEN_LEN = 32                  # Relay RELAY_SHARED_SECRET 최소 길이와 동일


# ── 예외 계층 ───────────────────────────────────────────────
# 모든 메시지는 고정 문자열 + 상태코드만 — token/URL/응답 본문을 절대 담지 않는다.
class TossRelayError(Exception):
    """Relay 호출 오류 기반 클래스 (네트워크·설정·기타 HTTP 오류 포함)."""


class TossRelayAuthError(TossRelayError):
    """Relay 인증 실패 (401) 또는 token 설정 오류."""


class TossRelayRateLimitError(TossRelayError):
    """429 — 호출 한도 초과. retry_after(초, 없으면 None) 보존.
    자동 sleep·재시도는 하지 않는다(호출측 정책)."""

    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class TossRelayTimeoutError(TossRelayError):
    """connect/read timeout."""


class TossRelayUpstreamError(TossRelayError):
    """Relay가 전달한 상류(Toss) 오류(502/503/504 등). error_code에 일반 code만 보존
    (TOSS_AUTH_FAILED/TOSS_IP_FORBIDDEN/TOSS_TIMEOUT/TOSS_BAD_RESPONSE/
    TOSS_UPSTREAM_ERROR/INTERNAL_ERROR 등)."""

    def __init__(self, message: str, error_code: str | None = None):
        super().__init__(message)
        self.error_code = error_code


class TossRelayResponseError(TossRelayError):
    """Relay 응답 본문 이상 — JSON 파싱 실패, provider 불일치, 필수 필드 누락,
    가격·timestamp 형식 오류."""


# ── 가격 스냅샷 ─────────────────────────────────────────────
@dataclass(frozen=True)
class RelayPrice:
    """Relay 경유 Toss 현재가 1건. last_price는 Decimal(문자열 원본 정밀도 보존),
    timestamp는 timezone-aware datetime(종목별 개별 기준시각 원본 보존).
    app/toss_overlay.py가 기대하는 속성 계약(symbol/last_price/currency/timestamp)과 동일."""
    symbol: str
    last_price: Decimal
    currency: str
    timestamp: dt.datetime


def normalize_symbols(symbols) -> list[str]:
    """조회용 심볼 정규화: 공백 제거 → 빈 값 제외 → 대문자(미국 ticker 정규화,
    한국 6자리 코드는 대문자화 무영향) → 입력 순서 유지 중복 제거.
    (app/toss.py와 같은 계약 — Relay 서버 쪽 TossClient가 최종 정규화를 다시 한다.)"""
    out: list[str] = []
    seen = set()
    for s in (symbols or []):
        v = str(s or "").strip().upper()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _parse_retry_after(value) -> int | None:
    try:
        n = int(str(value).strip())
        return n if n >= 0 else None
    except (TypeError, ValueError):
        return None


def _parse_timestamp(value) -> dt.datetime:
    """ISO 8601 문자열 → timezone-aware datetime. naive·형식 오류는 거부."""
    if not isinstance(value, str) or not value.strip():
        raise TossRelayResponseError("Relay 가격 응답 timestamp 형식 오류")
    try:
        ts = dt.datetime.fromisoformat(value.strip())
    except ValueError:
        raise TossRelayResponseError("Relay 가격 응답 timestamp 형식 오류") from None
    if ts.tzinfo is None or ts.tzinfo.utcoffset(ts) is None:
        raise TossRelayResponseError("Relay 가격 응답 timestamp에 timezone 없음")
    return ts


def _parse_price(value) -> Decimal:
    """last_price(Relay 계약상 문자열) → Decimal. 유한 양수만 허용."""
    if not isinstance(value, str) or not value.strip():
        raise TossRelayResponseError("Relay 가격 응답 last_price 형식 오류")
    try:
        p = Decimal(value.strip())
    except (InvalidOperation, ValueError):
        raise TossRelayResponseError("Relay 가격 응답 last_price 형식 오류") from None
    if not p.is_finite() or p <= 0:
        raise TossRelayResponseError("Relay 가격 응답 last_price 값 오류")
    return p


def _validate_base_url(base_url) -> str:
    """운영 설정 URL 검증: https만 허용, query/fragment/embedded credentials 거부,
    trailing slash 정규화. 오류 메시지에 URL 자체를 넣지 않는다."""
    raw = str(base_url or "").strip()
    if not raw:
        raise TossRelayError("Relay URL 미설정")
    parts = urlsplit(raw)
    if parts.scheme != "https":
        raise TossRelayError("Relay URL은 https만 허용")
    if not parts.netloc:
        raise TossRelayError("Relay URL 형식 오류")
    if parts.query or parts.fragment:
        raise TossRelayError("Relay URL에 query/fragment 사용 금지")
    if parts.username or parts.password:
        raise TossRelayError("Relay URL에 인증정보 포함 금지")
    return raw.rstrip("/")


class TossRelayClient:
    """Relay 클라이언트. base_url·relay_token은 생성자 주입(환경변수 연결은 호출측).

    - endpoint는 /v1/prices 하나로 고정 — 임의 URL·경로·HTTP method 입력 기능 없음.
    - token은 Authorization 헤더로만 전달(query/body 금지), repr·예외 비노출.
    - 429는 retry_after만 보존해 즉시 예외 — 자동 sleep·재시도 없음.
    - Toss OAuth token 재발급은 Relay 서버 내부 정책 — 이 모듈은 관여하지 않는다.
    """

    def __init__(self, base_url: str, relay_token: str, *,
                 session: requests.Session | None = None,
                 connect_timeout: float = CONNECT_TIMEOUT_SEC,
                 read_timeout: float = READ_TIMEOUT_SEC):
        self._base_url = _validate_base_url(base_url)
        token = str(relay_token or "")
        if not token.strip() or len(token) < MIN_TOKEN_LEN:
            raise TossRelayAuthError("Relay token 미설정 또는 최소 길이(32자) 미만")
        self._token = token
        self._session = session if session is not None else requests.Session()
        self._timeout = (float(connect_timeout), float(read_timeout))

    def __repr__(self) -> str:          # token 비노출 (repr가 로그에 찍혀도 안전)
        return f"TossRelayClient(base_url={self._base_url!r})"

    # ── 현재가 batch 조회 ────────────────────────────────────
    def get_prices(self, symbols) -> dict[str, RelayPrice]:
        """현재가 batch 조회 → {symbol: RelayPrice}.
        - 심볼: 공백/빈 값 제거, 대문자 정규화, 입력 순서 유지 중복 제거
        - 정규화 결과가 비면 HTTP 호출 없이 {} (빈 배열을 Relay로 보내지 않는다)
        - 200개 초과는 200개 단위 chunk로 분할 요청
        - 각 종목의 timestamp는 응답 원본 그대로(같은 batch라도 통일하지 않음)
        - 응답에서 누락된 심볼은 반환 dict에 넣지 않는다(호출측 fallback 판단)
        """
        wanted = normalize_symbols(symbols)
        if not wanted:
            return {}
        parsed: dict[str, RelayPrice] = {}
        for i in range(0, len(wanted), MAX_SYMBOLS_PER_REQUEST):
            chunk = wanted[i:i + MAX_SYMBOLS_PER_REQUEST]
            for item in self._request_prices(chunk):
                parsed[item.symbol] = item
        return {s: parsed[s] for s in wanted if s in parsed}

    # ── HTTP ────────────────────────────────────────────────
    def _request_prices(self, chunk: list[str]) -> list[RelayPrice]:
        try:
            resp = self._session.post(
                self._base_url + PRICES_PATH,
                json={"symbols": chunk},
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=self._timeout)
        except requests.Timeout:
            raise TossRelayTimeoutError("Relay 요청 timeout") from None
        except requests.RequestException:
            raise TossRelayError("Relay 네트워크 오류") from None
        self._raise_for_status(resp)
        return self._parse_price_items(resp)

    @staticmethod
    def _error_code(resp) -> str | None:
        """오류 응답의 {"error": code}에서 일반 code만 추출(그 외 본문은 버린다)."""
        try:
            body = resp.json()
        except ValueError:
            return None
        code = body.get("error") if isinstance(body, dict) else None
        return code if isinstance(code, str) and code else None

    @classmethod
    def _raise_for_status(cls, resp):
        """상태코드/오류 code → 예외 매핑. 메시지는 고정 문구 + 상태코드만."""
        status = resp.status_code
        if status == 200:
            return
        code = cls._error_code(resp)
        if status == 401:
            raise TossRelayAuthError("Relay 인증 실패 (401)")
        if status == 429 or code == "TOSS_RATE_LIMITED":
            retry_after = _parse_retry_after(
                getattr(resp, "headers", {}).get("Retry-After"))
            raise TossRelayRateLimitError(
                f"Relay 호출 한도 초과 ({status})", retry_after)
        if status in (502, 503, 504) or status >= 500:
            raise TossRelayUpstreamError(f"Relay 상류 오류 ({status})", error_code=code)
        raise TossRelayError(f"Relay 요청 실패 ({status})")

    @staticmethod
    def _parse_price_items(resp) -> list[RelayPrice]:
        try:
            body = resp.json()
        except ValueError:
            raise TossRelayResponseError("Relay 응답 JSON 파싱 실패") from None
        if not isinstance(body, dict):
            raise TossRelayResponseError("Relay 응답 형식 오류")
        if body.get("provider") != "Toss":
            raise TossRelayResponseError("Relay 응답 provider 오류")
        items = body.get("prices")
        if not isinstance(items, list):
            raise TossRelayResponseError("Relay 응답 prices 형식 오류")
        out = []
        for it in items:
            if not isinstance(it, dict):
                raise TossRelayResponseError("Relay 가격 응답 항목 형식 오류")
            sym = str(it.get("symbol") or "").strip().upper()
            if not sym:
                raise TossRelayResponseError("Relay 가격 응답 symbol 누락")
            out.append(RelayPrice(
                symbol=sym,
                last_price=_parse_price(it.get("last_price")),
                currency=str(it.get("currency") or "").strip().upper(),
                timestamp=_parse_timestamp(it.get("timestamp")),
            ))
        return out
