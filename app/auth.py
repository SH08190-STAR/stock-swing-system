"""
auth.py — 인증 모드·이메일 allowlist 순수 로직 (Streamlit 비의존)

대시보드 gate가 사용하는 판정 함수만 둔다. UI·세션·cookie는 다루지 않는다
(OIDC 세션 쿠키는 Streamlit 공식 st.login/st.user/st.logout이 전담).

정책:
- AUTH_MODE 미설정("") → password (기존 운영 동작 유지)
- "password" / "oidc" → 해당 모드 (앞뒤 공백 제거, 대소문자 무시)
- 그 외 값 → "invalid" (fail closed — 어떤 보호 화면도 열지 않음)
- allowlist 미설정·빈 목록 → 전원 거부 (fail closed)
- 이메일 비교는 strip + casefold 정규화 후 정확 일치만 허용
  (부분 일치·도메인 와일드카드 없음)
- 설정 우선순위: st.secrets(root) > 환경변수 > 기본값 (read_setting)
- OIDC는 [auth] 필수 설정 preflight 통과 전에는 로그인 버튼도 열지 않음
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

MODE_PASSWORD = "password"
MODE_OIDC = "oidc"
MODE_INVALID = "invalid"

# Streamlit 공식 OIDC([auth] 섹션) 필수 키 — 값 자체는 Secrets에만 존재한다.
OIDC_REQUIRED_KEYS = ("redirect_uri", "cookie_secret", "client_id",
                      "client_secret", "server_metadata_url")
OIDC_MIN_COOKIE_SECRET_BYTES = 32


def read_setting(name, default="", secrets=None, env=None):
    """설정 단일 읽기: st.secrets(root-level) > 환경변수 > 기본값.
    - secrets: Mapping 또는 None. 접근 실패·미존재·빈 문자열은 다음 단계로.
    - 문자열이 아닌 secrets 값(TOML 리스트 등)은 그대로 반환한다.
    - env: Mapping(기본 os.environ). 빈/공백 문자열은 미설정으로 취급."""
    if secrets is not None:
        try:
            if name in secrets:
                v = secrets[name]
                if isinstance(v, str):
                    if v.strip():
                        return v
                elif v is not None:
                    return v
        except Exception:
            pass
    e = os.environ if env is None else env
    try:
        v = e.get(name)
    except Exception:
        v = None
    if isinstance(v, str) and v.strip():
        return v
    return default


def oidc_config_ok(auth_section) -> bool:
    """[auth] 섹션 preflight. 통과해야만 로그인 버튼·st.login을 연다.
    실패 사유·키 이름·값은 반환하지 않는다(화면·로그 비노출 정책)."""
    if auth_section is None:
        return False
    vals = {}
    for key in OIDC_REQUIRED_KEYS:
        try:
            v = auth_section.get(key) if hasattr(auth_section, "get") else auth_section[key]
        except Exception:
            return False
        if not isinstance(v, str) or not v.strip():
            return False
        vals[key] = v.strip()
    parsed = urlparse(vals["redirect_uri"])
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    if not parsed.path.endswith("/oauth2callback"):
        return False
    if len(vals["cookie_secret"].encode("utf-8")) < OIDC_MIN_COOKIE_SECRET_BYTES:
        return False
    return True


def resolve_auth_mode(raw) -> str:
    """AUTH_MODE 설정값 → 모드 판정. 미설정은 password, 알 수 없는 값은 invalid."""
    if raw is None:
        return MODE_PASSWORD
    if not isinstance(raw, str):
        return MODE_INVALID
    v = raw.strip().casefold()
    if v == "":
        return MODE_PASSWORD
    if v in (MODE_PASSWORD, MODE_OIDC):
        return v
    return MODE_INVALID


def normalize_email(value) -> str:
    """이메일 정규화: 문자열만 인정, strip + casefold. 그 외 입력은 빈 문자열."""
    if not isinstance(value, str):
        return ""
    return value.strip().casefold()


def parse_allowed_emails(raw) -> list[str]:
    """허용 이메일 설정 → 정규화된 목록.
    문자열(콤마 구분)과 리스트/튜플(TOML 배열) 모두 지원. 빈 항목·중복 제거."""
    if isinstance(raw, str):
        items = raw.split(",")
    elif isinstance(raw, (list, tuple)):
        items = raw
    else:
        return []
    out = []
    for item in items:
        e = normalize_email(item)
        if e and e not in out:
            out.append(e)
    return out


def is_email_allowed(email, allowlist) -> bool:
    """정규화 후 정확 일치만 허용. email 없음·allowlist 비어있음 → False."""
    e = normalize_email(email)
    if not e:
        return False
    allowed = parse_allowed_emails(allowlist)
    if not allowed:
        return False
    return e in allowed
