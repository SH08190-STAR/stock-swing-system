"""toss.py — 토스증권 Open API 클라이언트 foundation (순수 모듈, Streamlit 비의존).

1차 범위: 토큰 발급·캐시 + 현재가 batch 조회 로직만. 대시보드·환경변수·DB·
QuotePair 연결은 하지 않는다(2차). 이 모듈은 어디에도 print/log를 남기지 않으며,
어떤 예외 문자열에도 client_id·client_secret·access_token·Authorization 헤더·
요청 body를 포함하지 않는다(고정 한글 메시지 + HTTP 상태코드만).

공식 명세 (https://openapi.tossinvest.com/openapi-docs):
- POST /oauth2/token — client_credentials, form-urlencoded,
  응답 access_token/token_type("Bearer")/expires_in(초). refresh token 없음.
  클라이언트당 활성 토큰 1개(재발급 시 이전 토큰 즉시 무효).
- GET /api/v1/prices?symbols=... — KR/US 본주·ETF 동일 endpoint,
  콤마 구분 최대 200종목, 항목별 symbol/lastPrice/currency/timestamp.
"""
from __future__ import annotations
import datetime as dt
import threading
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import requests

MODULE_API_VERSION = 1

BASE_URL = "https://openapi.tossinvest.com"
TOKEN_PATH = "/oauth2/token"
PRICES_PATH = "/api/v1/prices"
CONNECT_TIMEOUT_SEC = 3.0
READ_TIMEOUT_SEC = 5.0
TOKEN_REFRESH_MARGIN_SEC = 300          # 만료 5분 전부터는 재발급
MAX_SYMBOLS_PER_REQUEST = 200           # /api/v1/prices 공식 상한


# ── 예외 계층 ───────────────────────────────────────────────
# 모든 메시지는 고정 문자열 + 상태코드만 — secret/token/body를 절대 담지 않는다.
class TossApiError(Exception):
    """토스 API 오류 기반 클래스 (5xx·기타 HTTP 오류 포함)."""


class TossAuthError(TossApiError):
    """인증 실패 (토큰 발급 실패, 재발급 후에도 401)."""


class TossForbiddenError(TossApiError):
    """403 — 허용 IP 미등록 등 접근 거부."""


class TossRateLimitError(TossApiError):
    """429 — 호출 한도 초과. retry_after(초, 없으면 None) 보존.
    자동 sleep·재시도는 하지 않는다(호출측 정책)."""

    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class TossTimeoutError(TossApiError):
    """connect/read timeout."""


class TossResponseError(TossApiError):
    """응답 본문 이상 — JSON 파싱 실패, 필수 필드 누락, 가격·timestamp 형식 오류."""


# ── 가격 스냅샷 ─────────────────────────────────────────────
@dataclass(frozen=True)
class TossPrice:
    """토스 현재가 1건. last_price는 Decimal(문자열 원본 정밀도 보존),
    timestamp는 timezone-aware datetime(종목별 개별 기준시각 원본 보존)."""
    symbol: str
    last_price: Decimal
    currency: str
    timestamp: dt.datetime


def normalize_symbols(symbols) -> list[str]:
    """조회용 심볼 정규화: 공백 제거 → 빈 값 제외 → 대문자(미국 ticker 정규화,
    한국 6자리 숫자/영숫자 코드는 대문자화 무영향) → 입력 순서 유지 중복 제거."""
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
        raise TossResponseError("가격 응답 timestamp 형식 오류")
    try:
        ts = dt.datetime.fromisoformat(value.strip())
    except ValueError:
        raise TossResponseError("가격 응답 timestamp 형식 오류") from None
    if ts.tzinfo is None or ts.tzinfo.utcoffset(ts) is None:
        raise TossResponseError("가격 응답 timestamp에 timezone 없음")
    return ts


def _parse_price(value) -> Decimal:
    """lastPrice(문자열 권장) → Decimal. 유한 양수만 허용."""
    if isinstance(value, bool) or value is None:
        raise TossResponseError("가격 응답 lastPrice 형식 오류")
    try:
        p = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise TossResponseError("가격 응답 lastPrice 형식 오류") from None
    if not p.is_finite() or p <= 0:
        raise TossResponseError("가격 응답 lastPrice 값 오류")
    return p


class TossClient:
    """토스 Open API 클라이언트. credentials는 생성자 주입(환경변수 연결은 2차).

    - 토큰은 인스턴스 내부에만 캐시(만료 5분 전 재발급, thread lock으로 중복 발급 방지).
      토스는 클라이언트당 활성 토큰 1개만 허용하므로 프로세스당 인스턴스 1개 권장.
    - 429는 retry_after만 보존해 즉시 예외 — 자동 sleep·재시도 없음.
    - 401은 토큰 폐기 후 정확히 1회 재발급·재요청, 재차 401이면 TossAuthError.
    """

    def __init__(self, client_id: str, client_secret: str, *,
                 session: requests.Session | None = None,
                 base_url: str = BASE_URL,
                 connect_timeout: float = CONNECT_TIMEOUT_SEC,
                 read_timeout: float = READ_TIMEOUT_SEC,
                 now_fn=None):
        if not client_id or not client_secret:
            raise TossAuthError("클라이언트 credentials 미설정")
        self._client_id = str(client_id)
        self._client_secret = str(client_secret)
        self._session = session if session is not None else requests.Session()
        self._base_url = str(base_url).rstrip("/")
        self._timeout = (float(connect_timeout), float(read_timeout))
        self._now = now_fn or (lambda: dt.datetime.now(dt.timezone.utc))
        self._lock = threading.Lock()
        self._token: str | None = None
        self._token_expires_at: dt.datetime | None = None

    def __repr__(self) -> str:          # secret 비노출 (repr가 로그에 찍혀도 안전)
        return f"TossClient(base_url={self._base_url!r})"

    # ── 토큰 관리 ───────────────────────────────────────────
    def _token_usable_locked(self) -> bool:
        if self._token is None or self._token_expires_at is None:
            return False
        margin = dt.timedelta(seconds=TOKEN_REFRESH_MARGIN_SEC)
        return self._now() < self._token_expires_at - margin

    def _get_token(self) -> str:
        """유효 토큰 반환(없거나 만료 5분 전이면 lock 안에서 1회만 발급)."""
        with self._lock:
            if self._token_usable_locked():
                return self._token
            return self._issue_token_locked()

    def _discard_token(self, token: str):
        """401을 받은 그 토큰만 폐기(다른 스레드가 이미 재발급했으면 보존)."""
        with self._lock:
            if self._token == token:
                self._token = None
                self._token_expires_at = None

    def _issue_token_locked(self) -> str:
        try:
            resp = self._session.post(
                self._base_url + TOKEN_PATH,
                data={"grant_type": "client_credentials",
                      "client_id": self._client_id,
                      "client_secret": self._client_secret},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=self._timeout)
        except requests.Timeout:
            raise TossTimeoutError("토큰 발급 timeout") from None
        except requests.RequestException:
            raise TossApiError("토큰 발급 네트워크 오류") from None
        if resp.status_code == 401:     # 발급 자체의 401 = 잘못된 credentials
            raise TossAuthError("토큰 발급 인증 실패 (401)")
        self._raise_for_status(resp, what="토큰 발급")
        try:
            body = resp.json()
        except ValueError:
            raise TossResponseError("토큰 응답 JSON 파싱 실패") from None
        if not isinstance(body, dict):
            raise TossResponseError("토큰 응답 형식 오류")
        token = body.get("access_token")
        token_type = body.get("token_type")
        expires_in = body.get("expires_in")
        if not isinstance(token, str) or not token.strip():
            raise TossResponseError("토큰 응답 access_token 누락")
        if not isinstance(token_type, str) or token_type.strip().lower() != "bearer":
            raise TossResponseError("토큰 응답 token_type 오류")
        if isinstance(expires_in, bool) or not isinstance(expires_in, (int, float)) \
                or expires_in <= 0:
            raise TossResponseError("토큰 응답 expires_in 오류")
        self._token = token
        self._token_expires_at = self._now() + dt.timedelta(seconds=float(expires_in))
        return token

    # ── 공통 HTTP ───────────────────────────────────────────
    @staticmethod
    def _raise_for_status(resp, what: str):
        """상태코드 → 예외 매핑. 메시지는 고정 문구 + 상태코드만(응답 본문 비포함)."""
        code = resp.status_code
        if code == 403:
            raise TossForbiddenError(f"{what} 접근 거부 (403) — 허용 IP 등록 확인 필요")
        if code == 429:
            retry_after = _parse_retry_after(
                getattr(resp, "headers", {}).get("Retry-After"))
            raise TossRateLimitError(f"{what} 호출 한도 초과 (429)", retry_after)
        if code == 404:                 # 전체 요청 404 — 부분 누락/성공으로 처리하지 않음
            raise TossApiError(f"{what} 대상을 찾을 수 없음 (404)")
        if code >= 500:
            raise TossApiError(f"{what} 서버 오류 ({code})")
        if code >= 400:                 # 401은 호출측에서 별도 처리
            raise TossApiError(f"{what} 요청 실패 ({code})")

    def _authorized_get(self, path: str, params: dict, what: str):
        """Bearer GET. 첫 401은 해당 토큰 폐기 → 정확히 1회 재발급·재요청,
        두 번째 401이면 TossAuthError."""
        token = self._get_token()
        resp = self._do_get(path, params, token, what)
        if resp.status_code == 401:
            self._discard_token(token)
            token = self._get_token()   # 재발급 실패 시 여기서 예외
            resp = self._do_get(path, params, token, what)
            if resp.status_code == 401:
                raise TossAuthError(f"{what} 인증 실패 (재발급 후에도 401)")
        self._raise_for_status(resp, what=what)
        return resp

    def _do_get(self, path: str, params: dict, token: str, what: str):
        try:
            return self._session.get(
                self._base_url + path, params=params,
                headers={"Authorization": f"Bearer {token}"},
                timeout=self._timeout)
        except requests.Timeout:
            raise TossTimeoutError(f"{what} timeout") from None
        except requests.RequestException:
            raise TossApiError(f"{what} 네트워크 오류") from None

    # ── 현재가 batch 조회 ────────────────────────────────────
    def get_prices(self, symbols) -> dict[str, TossPrice]:
        """현재가 batch 조회 → {symbol: TossPrice}. KR/US 본주·ETF 동일 endpoint.
        - 심볼: 공백/빈 값 제거, 대문자 정규화, 입력 순서 유지 중복 제거
        - 200개 초과는 200개 단위 chunk로 분할 요청
        - 각 종목의 timestamp는 응답 원본 그대로(같은 batch라도 통일하지 않음)
        - 200 응답에서 누락된 심볼은 반환 dict에 넣지 않는다(호출측 fallback 판단)
        - 200 응답의 개별 item 불량(가격·timestamp·symbol 형식 오류)은 그 item만
          제외하고 정상 item은 반환한다 — 일시적 데이터 지연 종목 1개가 batch
          전체를 실패시키지 않는다. 단 항목이 있는데 전부 불량이면 응답 전체
          손상으로 보고 TossResponseError(조용히 빈 결과로 숨기지 않음).
        """
        wanted = normalize_symbols(symbols)
        if not wanted:
            return {}
        parsed: dict[str, TossPrice] = {}
        for i in range(0, len(wanted), MAX_SYMBOLS_PER_REQUEST):
            chunk = wanted[i:i + MAX_SYMBOLS_PER_REQUEST]
            resp = self._authorized_get(
                PRICES_PATH, {"symbols": ",".join(chunk)}, what="현재가 조회")
            for item in self._parse_price_items(resp):
                parsed[item.symbol] = item
        # 입력 순서 유지(응답에 존재하는 심볼만)
        return {s: parsed[s] for s in wanted if s in parsed}

    @staticmethod
    def _parse_price_items(resp) -> list[TossPrice]:
        """가격 응답 파싱. 컨테이너(JSON·result 목록) 오류는 TossResponseError,
        item 단위 불량은 해당 item만 제외(부분 반환). 빈 목록은 정상 빈 결과.
        항목이 있는데 유효 item이 0개면 TossResponseError — 전체 손상을 숨기지 않는다.
        예외 메시지는 고정 문구만(원본 item/body 비포함)."""
        try:
            body = resp.json()
        except ValueError:
            raise TossResponseError("가격 응답 JSON 파싱 실패") from None
        items = body.get("result") if isinstance(body, dict) else body
        if not isinstance(items, list):
            raise TossResponseError("가격 응답 result 형식 오류")
        out = []
        for it in items:
            parsed = TossClient._parse_one_price_item(it)
            if parsed is not None:
                out.append(parsed)
        if items and not out:
            raise TossResponseError("가격 응답 유효 항목 없음")
        return out

    @staticmethod
    def _parse_one_price_item(it) -> TossPrice | None:
        """item 1건 파싱 — 불량(비dict·symbol 누락·가격/timestamp 형식 오류)은 None.
        누락된 심볼은 반환 dict에 없음 → 호출측이 기존 계약대로 fallback한다."""
        if not isinstance(it, dict):
            return None
        sym = str(it.get("symbol") or "").strip().upper()
        if not sym:
            return None
        try:
            price = _parse_price(it.get("lastPrice"))
            ts = _parse_timestamp(it.get("timestamp"))
        except TossResponseError:
            return None
        return TossPrice(symbol=sym, last_price=price,
                         currency=str(it.get("currency") or "").strip().upper(),
                         timestamp=ts)
