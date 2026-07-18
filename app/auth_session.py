"""
auth_session.py — 대시보드 30일 로그인 유지 토큰 + cookie component (v2)

계약
- 토큰 형식: "v1.<만료 unix초>.<서명>"  (서명 = HMAC-SHA256 → base64url, 패딩 없음)
- 서명키 파생(도메인 구분 HMAC):
  derived_key = HMAC-SHA256(key=APP_SESSION_SECRET, msg=b"zpick-session-v1\\x00" + APP_PASSWORD)
  → secret 또는 비밀번호가 바뀌면 기존 토큰은 전부 자동 무효.
- APP_SESSION_SECRET은 UTF-8 기준 최소 32바이트. 부족·미설정이면 derive_key가
  None을 반환하고 30일 유지만 비활성(호출측은 세션 로그인 fallback, crash 없음).
- 토큰에는 만료시각만 담는다. 비밀번호·secret·기기정보는 절대 담지 않는다.
- cookie 쓰기/삭제는 st.components.v2 component "zpick_cookie_action" 1개로
  수행한다(모듈 로드 시 1회 등록, 구버전 embed API 미사용, 외부 JS/CDN 없음).
  동적 값(token 등)은 JS 소스에 포맷팅하지 않고 mount의 data로만 전달하며,
  JS가 cookie name·token charset을 다시 검증한다. 완료 시
  setTriggerValue("completed", "set"|"delete")로 신호를 보낸다.
- token·비밀번호·secret은 로그·화면·예외 메시지에 노출하지 않는다.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
import time

import streamlit as st

COOKIE_NAME = "zpick_session"
COMPONENT_NAME = "zpick_cookie_action"
TTL_SECONDS = 30 * 24 * 3600          # 30일
MAX_FUTURE_SKEW_SEC = 300             # 만료시각이 now+TTL을 이 이상 초과하면 위조로 간주
MIN_SECRET_BYTES = 32                 # APP_SESSION_SECRET 최소 길이(UTF-8 bytes)
_MAX_TOKEN_LEN = 200
# v1.<exp digits>.<base64url 서명>  — sha256 b64url(무패딩)은 43자
_TOKEN_RE = re.compile(r"^v1\.\d{1,20}\.[A-Za-z0-9_-]{20,100}$")


# ── 토큰 발급·검증 (순수 함수) ───────────────────────────────
def derive_key(session_secret: str, app_password: str) -> bytes | None:
    """도메인 구분 HMAC 서명키 파생. secret이 없거나 32바이트 미만·비밀번호
    미설정이면 None(30일 유지 비활성). 원문은 어디에도 저장·출력하지 않는다."""
    if not session_secret or not app_password:
        return None
    secret_b = session_secret.encode("utf-8")
    if len(secret_b) < MIN_SECRET_BYTES:
        return None
    return hmac.new(secret_b,
                    b"zpick-session-v1\x00" + app_password.encode("utf-8"),
                    hashlib.sha256).digest()


def _sign(key: bytes, payload: str) -> str:
    sig = hmac.new(key, payload.encode("ascii"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).rstrip(b"=").decode("ascii")


def issue_token(key: bytes, now: float | None = None, ttl: int = TTL_SECONDS) -> str:
    """만료시각만 담은 서명 토큰 발급."""
    exp = int((time.time() if now is None else now) + ttl)
    payload = f"v1.{exp}"
    return f"{payload}.{_sign(key, payload)}"


def verify_token(key: bytes | None, token: str | None, now: float | None = None) -> bool:
    """형식·서명·만료 검증. 실패 사유는 구분하지 않고 False만 반환(정보 비노출).
    - base64url strict decode + digest 길이 검사 + hmac.compare_digest
    - 만료시각이 now+TTL+skew를 초과하는 비정상 미래값은 서명이 맞아도 거부"""
    if not key or not token or len(token) > _MAX_TOKEN_LEN:
        return False
    if not _TOKEN_RE.fullmatch(token) or token.count(".") != 2:
        return False
    payload, _, sig = token.rpartition(".")
    try:
        exp = int(payload.split(".", 1)[1])
    except (IndexError, ValueError):
        return False
    try:
        sig_raw = base64.b64decode(
            sig.replace("-", "+").replace("_", "/") + "=" * (-len(sig) % 4),
            validate=True)
    except (binascii.Error, ValueError):
        return False
    if len(sig_raw) != hashlib.sha256().digest_size:
        return False
    expected = hmac.new(key, payload.encode("ascii"), hashlib.sha256).digest()
    if not hmac.compare_digest(expected, sig_raw):
        return False
    t = time.time() if now is None else now
    if exp - t > TTL_SECONDS + MAX_FUTURE_SKEW_SEC:
        return False                  # TTL 허용 범위를 초과한 미래 만료 — 거부
    return t < exp


def _assert_token_safe(token: str) -> None:
    if not token or len(token) > _MAX_TOKEN_LEN or not _TOKEN_RE.fullmatch(token):
        raise ValueError("invalid session token format")


# ── cookie component (st.components.v2, 모듈 로드 시 1회 등록) ──────────────
# JS는 고정 문자열 — 사용자 입력·토큰을 소스에 포맷팅하지 않는다(전부 data 경유).
# JS가 cookie name(고정 zpick_session)과 token charset을 다시 검증하고,
# 완료 시 setTriggerValue("completed", action)을 보낸다. Domain 속성 미지정.
# secure: data.secure === true → 항상, false → 금지, null → https일 때만(자동).
_COOKIE_JS = """
export default function(component) {
    const { data, setTriggerValue } = component;
    try {
        if (!data || typeof data !== "object") { return; }
        if (String(data.name || "") !== "zpick_session") { return; }
        const action = data.action;
        const secure = (data.secure === true) ||
            (data.secure == null && window.location.protocol === "https:");
        if (action === "set") {
            const value = String(data.value || "");
            if (!/^v1\\.\\d{1,20}\\.[A-Za-z0-9_-]{20,100}$/.test(value)) { return; }
            const maxAge = Number(data.max_age);
            if (!Number.isFinite(maxAge) || maxAge <= 0 || maxAge > 2592000) { return; }
            let s = data.name + "=" + value + "; Max-Age=" + Math.floor(maxAge) +
                "; Path=/; SameSite=Lax";
            if (secure) { s += "; Secure"; }
            document.cookie = s;
            setTriggerValue("completed", "set");
        } else if (action === "delete") {
            let s = data.name + "=; Max-Age=0" +
                "; expires=Thu, 01 Jan 1970 00:00:00 GMT; Path=/; SameSite=Lax";
            if (secure) { s += "; Secure"; }
            document.cookie = s;
            setTriggerValue("completed", "delete");
        }
    } catch (e) { /* cookie 실패는 조용히 무시 — 세션 로그인은 유지된다 */ }
}
"""

try:
    # 모듈 로드 시 정확히 1회 등록. 등록 실패(구버전 등)면 None — 30일 유지만 비활성.
    _cookie_component = st.components.v2.component(COMPONENT_NAME, js=_COOKIE_JS)
except Exception:
    _cookie_component = None


def cookie_set_data(token: str) -> dict:
    """set mount용 data. 토큰은 서버 생성값만 허용(charset 재검증)."""
    _assert_token_safe(token)
    return {"action": "set", "name": COOKIE_NAME, "value": token,
            "max_age": TTL_SECONDS, "secure": None}


def cookie_delete_data() -> dict:
    return {"action": "delete", "name": COOKIE_NAME, "value": None,
            "max_age": 0, "secure": None}


def render_cookie_set(token: str, *, on_completed=None,
                      key: str = "auth_cookie_set", component=None):
    """cookie set component 마운트. 실패해도 예외 전파 없음(세션 로그인 유지).
    component 인자는 테스트 주입용 — 기본은 모듈 로드 시 등록된 component."""
    data = cookie_set_data(token)     # 형식 위반은 여기서 ValueError(마운트 전)
    comp = _cookie_component if component is None else component
    if comp is None:
        return None
    try:
        return comp(key=key, data=data, on_completed_change=on_completed)
    except Exception:
        return None


def render_cookie_delete(*, on_completed=None,
                         key: str = "auth_cookie_delete", component=None):
    """cookie delete component 마운트. 실패해도 예외 전파 없음."""
    comp = _cookie_component if component is None else component
    if comp is None:
        return None
    try:
        return comp(key=key, data=cookie_delete_data(), on_completed_change=on_completed)
    except Exception:
        return None
