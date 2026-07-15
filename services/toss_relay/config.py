"""config.py — Toss Relay 환경 설정 (Fly secrets → 환경변수).

필수 환경변수 3개(RELAY_SHARED_SECRET / TOSS_CLIENT_ID / TOSS_CLIENT_SECRET)가
하나라도 없거나 RELAY_SHARED_SECRET이 32자 미만이면 서비스가 시작되지 않는다
(fail fast). 오류 메시지는 고정 문구만 사용하며 실제 값·길이·prefix를 담지 않는다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

MIN_RELAY_SECRET_LEN = 32


class RelayConfigError(RuntimeError):
    """설정 오류 — 메시지는 고정 문구만 (secret 값 비노출)."""


@dataclass(frozen=True, repr=False)
class RelayConfig:
    """Relay 설정. repr/str에 secret이 노출되지 않도록 repr을 고정한다."""
    relay_shared_secret: str = field(repr=False)
    toss_client_id: str = field(repr=False)
    toss_client_secret: str = field(repr=False)

    def __repr__(self) -> str:
        return "RelayConfig(<redacted>)"


def validate_config(cfg: RelayConfig) -> None:
    """필수 값 존재 + shared secret 최소 길이 검증. 실패 시 RelayConfigError."""
    if not isinstance(cfg.toss_client_id, str) or not cfg.toss_client_id.strip():
        raise RelayConfigError("TOSS_CLIENT_ID 미설정")
    if not isinstance(cfg.toss_client_secret, str) or not cfg.toss_client_secret.strip():
        raise RelayConfigError("TOSS_CLIENT_SECRET 미설정")
    secret = cfg.relay_shared_secret
    if not isinstance(secret, str) or len(secret) < MIN_RELAY_SECRET_LEN:
        raise RelayConfigError("RELAY_SHARED_SECRET 미설정 또는 최소 길이(32자) 미만")


def load_config(env=None) -> RelayConfig:
    """환경변수에서 설정 로드 + 검증. env 미지정 시 os.environ 사용."""
    source = os.environ if env is None else env
    cfg = RelayConfig(
        relay_shared_secret=str(source.get("RELAY_SHARED_SECRET") or ""),
        toss_client_id=str(source.get("TOSS_CLIENT_ID") or ""),
        toss_client_secret=str(source.get("TOSS_CLIENT_SECRET") or ""),
    )
    validate_config(cfg)
    return cfg
