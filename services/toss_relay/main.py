"""main.py — 토스증권 시세 전용 Relay (FastAPI, server-to-server 전용).

공개 endpoint는 정확히 두 개:
- GET  /healthz    — 인증 불필요, Toss 미호출, {"status":"ok"}만 반환
- POST /v1/prices  — Bearer(RELAY_SHARED_SECRET) 인증 후 app.toss.TossClient로
                     현재가 batch 조회. 임의 URL/endpoint/method 전달 불가.

보안 경계:
- 인증 비교는 hmac.compare_digest(상수 시간). 실패 사유와 무관하게 동일한 401.
- 어떤 응답·예외에도 Toss access token·client secret·원본 상류 응답을 담지 않는다
  (app.toss 예외 메시지는 고정 문구 + 상태코드만이라는 계약을 그대로 활용).
- CORS 미허용(브라우저 직접 호출 대상 아님). 모든 응답 Cache-Control: no-store.
- TossClient는 프로세스당 1개 lazy 생성·재사용 (uvicorn worker 1개 전제 —
  토스는 클라이언트당 활성 토큰 1개). import·health check만으로는 토큰 발급 없음.
"""
from __future__ import annotations

import threading
from hmac import compare_digest as _compare_digest

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import (BaseModel, ConfigDict, Field, StrictStr, ValidationError,
                      field_validator)
from starlette.concurrency import run_in_threadpool

from app import toss
from services.toss_relay.config import RelayConfig, load_config, validate_config

RELAY_API_VERSION = 1
MAX_SYMBOLS = toss.MAX_SYMBOLS_PER_REQUEST      # 200 — foundation 계약 재사용
MAX_SYMBOL_LEN = 32
MAX_RETRY_AFTER_SEC = 3600                      # 이 범위 밖 Retry-After는 전달하지 않음


class PricesRequest(BaseModel):
    """POST /v1/prices 요청 본문. symbols 외 필드는 전부 거부(extra=forbid)."""
    model_config = ConfigDict(extra="forbid")
    symbols: list[StrictStr] = Field(min_length=1, max_length=MAX_SYMBOLS)

    @field_validator("symbols")
    @classmethod
    def _each_symbol(cls, value: list[str]) -> list[str]:
        for s in value:
            if not s.strip():
                raise ValueError("빈 심볼")
            if len(s.strip()) > MAX_SYMBOL_LEN:
                raise ValueError("심볼 길이 초과")
        return value


def _error(status: int, code: str, message: str, headers=None) -> JSONResponse:
    """오류 응답 — error code + 고정 짧은 메시지만 (상류 본문·예외 repr 비포함)."""
    return JSONResponse(status_code=status,
                        content={"error": code, "message": message},
                        headers=headers)


def _default_toss_client_factory(cfg: RelayConfig) -> "toss.TossClient":
    return toss.TossClient(cfg.toss_client_id, cfg.toss_client_secret)


def create_app(config: RelayConfig | None = None,
               toss_client_factory=None) -> FastAPI:
    """Relay 앱 factory. config 미지정 시 환경변수 로드 — 검증 실패면 시작 실패.

    uvicorn 실행: uvicorn services.toss_relay.main:create_app --factory --workers 1
    """
    cfg = load_config() if config is None else config
    validate_config(cfg)                        # 직접 주입된 config도 동일 기준 검증
    factory = toss_client_factory or _default_toss_client_factory
    secret_bytes = cfg.relay_shared_secret.encode("utf-8")

    # 공개 스키마/문서 endpoint 비활성 — 허용 endpoint 2개 외 전부 404
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    app.state.toss_client = None
    client_lock = threading.Lock()

    def _authorized(request: Request) -> bool:
        header = request.headers.get("Authorization") or ""
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer":
            return False
        token = token.strip()
        if not token:
            return False
        return _compare_digest(token.encode("utf-8"), secret_bytes)

    def _get_client():
        """프로세스(앱)당 TossClient 1개 lazy 생성 — 첫 인증된 요청에서만."""
        client = app.state.toss_client
        if client is None:
            with client_lock:
                if app.state.toss_client is None:
                    app.state.toss_client = factory(cfg)
                client = app.state.toss_client
        return client

    @app.middleware("http")
    async def _response_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Relay-Api-Version"] = str(RELAY_API_VERSION)
        return response

    @app.get("/healthz")
    async def healthz():
        # Toss 호출·토큰 발급·secret 접근 없음. 내부 상세정보 비반환.
        return {"status": "ok"}

    @app.post("/v1/prices")
    async def prices(request: Request):
        if not _authorized(request):
            return _error(401, "UNAUTHORIZED", "인증 실패")
        try:
            payload = await request.json()
        except Exception:
            return _error(400, "INVALID_REQUEST", "요청 형식 오류")
        try:
            req = PricesRequest.model_validate(payload)
        except ValidationError:
            return _error(400, "INVALID_REQUEST", "요청 형식 오류")

        try:
            client = _get_client()
            result = await run_in_threadpool(client.get_prices, req.symbols)
        except toss.TossAuthError:
            return _error(503, "TOSS_AUTH_FAILED", "상류 인증 실패")
        except toss.TossForbiddenError:
            return _error(502, "TOSS_IP_FORBIDDEN", "상류 접근 거부")
        except toss.TossRateLimitError as exc:
            headers = {}
            retry_after = getattr(exc, "retry_after", None)
            if (isinstance(retry_after, int) and not isinstance(retry_after, bool)
                    and 0 <= retry_after <= MAX_RETRY_AFTER_SEC):
                headers["Retry-After"] = str(retry_after)
            return _error(429, "TOSS_RATE_LIMITED", "상류 호출 한도 초과", headers)
        except toss.TossTimeoutError:
            return _error(504, "TOSS_TIMEOUT", "상류 응답 시간 초과")
        except toss.TossResponseError:
            return _error(502, "TOSS_BAD_RESPONSE", "상류 응답 형식 오류")
        except toss.TossApiError:
            return _error(502, "TOSS_UPSTREAM_ERROR", "상류 오류")
        except Exception:
            return _error(500, "INTERNAL_ERROR", "내부 오류")

        # 응답에 없는 심볼은 항목을 만들지 않는다(호출측 fallback 판단).
        return JSONResponse({
            "provider": "Toss",
            "prices": [{
                "symbol": p.symbol,
                "last_price": str(p.last_price),        # Decimal → 문자열
                "currency": p.currency,
                "timestamp": p.timestamp.isoformat(),   # timezone-aware 원본 유지
            } for p in result.values()],
        })

    return app
