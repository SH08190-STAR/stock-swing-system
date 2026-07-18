"""
tests/test_auth_session.py — 30일 로그인 유지(app/auth_session.py + gate 흐름) 검증.
네트워크·DB·실제 브라우저 없이 순수 함수와 stub으로 검증한다.
"""
import hashlib
import hmac as hmac_mod
import importlib
import importlib.util
import inspect
import os
from types import SimpleNamespace

import pytest

from app import auth_session as a

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECRET = "s" * 40                     # 32바이트 이상
PASSWORD = "correct-horse-battery"


def _key():
    return a.derive_key(SECRET, PASSWORD)


def _dash():
    p = os.path.join(ROOT, "dashboard", "app.py")
    spec = importlib.util.spec_from_file_location("dash_for_auth_test", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _dash_stubbed():
    """dash 모듈 로드 후 st/config를 stub으로 교체(인증 흐름 로직만 검사).
    stub st에는 rerun이 없다 — 어떤 경로든 st.rerun() 호출 시 AttributeError로 실패."""
    m = _dash()
    m.st = SimpleNamespace(session_state={})
    m.config = SimpleNamespace(APP_PASSWORD="pw123", APP_SESSION_SECRET=SECRET)
    return m


class _FakeComponent:
    """v2 component mount callable stub — kwargs 캡처."""
    def __init__(self, raise_on_call=False):
        self.calls = []
        self.raise_on_call = raise_on_call

    def __call__(self, **kwargs):
        if self.raise_on_call:
            raise RuntimeError("mount failed")
        self.calls.append(kwargs)
        return SimpleNamespace(completed=None)


# ── 서명키 파생 (도메인 구분 HMAC) ──────────────────────────
def test_derive_key_domain_separated_hmac_contract():
    expected = hmac_mod.new(SECRET.encode("utf-8"),
                            b"zpick-session-v1\x00" + PASSWORD.encode("utf-8"),
                            hashlib.sha256).digest()
    assert _key() == expected
    assert len(_key()) == 32


def test_derive_key_rejects_short_or_missing_secret():
    assert a.derive_key("short", PASSWORD) is None          # 32바이트 미만
    assert a.derive_key("x" * 31, PASSWORD) is None
    assert a.derive_key("", PASSWORD) is None
    assert a.derive_key(SECRET, "") is None                 # 비밀번호 미설정
    # UTF-8 바이트 기준: 한글 11자 = 33바이트 → 허용
    assert a.derive_key("가" * 11, PASSWORD) is not None


def test_old_tokens_rejected_after_secret_change():
    tok = a.issue_token(_key(), now=1_000_000.0)
    new_key = a.derive_key("t" * 40, PASSWORD)              # secret 변경
    assert new_key != _key()
    assert not a.verify_token(new_key, tok, now=1_000_000.0)


def test_old_tokens_rejected_after_password_change():
    tok = a.issue_token(_key(), now=1_000_000.0)
    new_key = a.derive_key(SECRET, "new-password")          # 비밀번호 변경
    assert new_key != _key()
    assert not a.verify_token(new_key, tok, now=1_000_000.0)


# ── 토큰 발급·검증 ──────────────────────────────────────────
def test_issue_and_verify_roundtrip():
    k = _key()
    tok = a.issue_token(k, now=1_000_000.0)
    assert a.verify_token(k, tok, now=1_000_000.0 + 10)


def test_token_contains_no_password_or_secret():
    tok = a.issue_token(_key(), now=1_000_000.0)
    assert PASSWORD not in tok
    assert SECRET not in tok
    assert tok.startswith("v1.")


def test_ttl_is_30_days():
    assert a.TTL_SECONDS == 30 * 24 * 3600
    tok = a.issue_token(_key(), now=0.0)
    assert int(tok.split(".")[1]) == a.TTL_SECONDS


def test_expired_token_rejected():
    k = _key()
    tok = a.issue_token(k, now=1_000_000.0)
    assert not a.verify_token(k, tok, now=1_000_000.0 + a.TTL_SECONDS)      # 경계 포함
    assert not a.verify_token(k, tok, now=1_000_000.0 + a.TTL_SECONDS + 1)


def test_token_with_excessive_future_expiry_rejected():
    """서명이 유효해도 만료가 30일 허용 범위를 과도하게 초과하면 거부."""
    k = _key()
    ok = a.issue_token(k, now=1_000_000.0, ttl=a.TTL_SECONDS)
    assert a.verify_token(k, ok, now=1_000_000.0)                            # 정상 30일
    too_far = a.issue_token(k, now=1_000_000.0,
                            ttl=a.TTL_SECONDS + a.MAX_FUTURE_SKEW_SEC + 60)
    assert not a.verify_token(k, too_far, now=1_000_000.0)
    doubled = a.issue_token(k, now=1_000_000.0, ttl=a.TTL_SECONDS * 2)
    assert not a.verify_token(k, doubled, now=1_000_000.0)


def test_tampered_token_rejected():
    k = _key()
    tok = a.issue_token(k, now=1_000_000.0)
    head, sig = tok.rsplit(".", 1)
    flipped = ("A" if sig[0] != "A" else "B") + sig[1:]
    assert not a.verify_token(k, f"{head}.{flipped}", now=1_000_000.0)      # 서명 변조
    exp = int(head.split(".")[1])
    assert not a.verify_token(k, f"v1.{exp - 100}.{sig}", now=1_000_000.0)  # 만료 변조


def test_verify_rejects_garbage_and_malformed_inputs():
    k = _key()
    tok = a.issue_token(k, now=1_000_000.0)
    assert not a.verify_token(None, tok)                    # 키 없음(기능 비활성)
    assert not a.verify_token(k, None)
    assert not a.verify_token(k, "")
    assert not a.verify_token(k, "logged_in=true")          # 위조 평문
    assert not a.verify_token(k, "v1.abc.def")
    assert not a.verify_token(k, "v2.123." + "a" * 43)
    assert not a.verify_token(k, "v1.1." + "a" * 500)       # 과대 길이
    assert not a.verify_token(k, tok + ".extra", now=1_000_000.0)   # 추가 구분자
    assert not a.verify_token(k, tok.replace(".", "..", 1), now=1_000_000.0)


# ── components.v2 전환 계약 ─────────────────────────────────
def _src(relpath):
    with open(os.path.join(ROOT, relpath), encoding="utf-8") as f:
        return f.read()


def test_no_components_v1_or_iframe_usage():
    """신규 인증 경로에 deprecated v1 iframe API 사용 0."""
    for rel in ("app/auth_session.py", "dashboard/app.py"):
        src = _src(rel)
        assert "components.v1" not in src, rel
        assert "components.html" not in src, rel
    assert "iframe" not in _src("app/auth_session.py").lower()


def test_component_registered_exactly_once_at_module_load():
    """모듈 로드 시 등록 1회 — render 호출은 재등록하지 않는다."""
    import streamlit.components.v2 as v2
    calls = []
    real = v2.component

    def counting(name, **kwargs):
        calls.append(name)
        return _FakeComponent()

    try:
        v2.component = counting
        mod = importlib.reload(a)
        assert calls == [a.COMPONENT_NAME]                  # 정확히 1회
        fake = _FakeComponent()
        mod.render_cookie_set(mod.issue_token(_key()), component=fake)
        mod.render_cookie_delete(component=fake)
        assert calls == [a.COMPONENT_NAME]                  # 호출로 재등록 없음
    finally:
        v2.component = real
        importlib.reload(a)                                 # 실제 component로 복원


def test_token_not_formatted_into_js_source():
    """동적 값은 JS 소스에 삽입되지 않고 data로만 전달된다."""
    tok = a.issue_token(_key(), now=1_000_000.0)
    fake = _FakeComponent()
    a.render_cookie_set(tok, component=fake)
    assert tok not in a._COOKIE_JS                          # JS는 고정 문자열
    assert "{" not in a.COMPONENT_NAME
    (call,) = fake.calls
    assert call["data"]["value"] == tok                     # data 경유 전달
    assert call["data"] == {"action": "set", "name": "zpick_session",
                            "value": tok, "max_age": a.TTL_SECONDS, "secure": None}


def test_delete_data_contract():
    fake = _FakeComponent()
    a.render_cookie_delete(component=fake)
    (call,) = fake.calls
    assert call["data"]["action"] == "delete"
    assert call["data"]["name"] == "zpick_session"
    assert call["data"]["max_age"] == 0


def test_js_source_contract_set_and_delete_signals():
    """JS: name·charset 재검증 + set/delete cookie 속성 + 완료 신호."""
    js = a._COOKIE_JS
    assert 'setTriggerValue("completed", "set")' in js
    assert 'setTriggerValue("completed", "delete")' in js
    assert "zpick_session" in js                            # cookie name 재검증
    assert "A-Za-z0-9_-" in js                              # token charset 재검증
    assert "Max-Age=" in js and "Path=/; SameSite=Lax" in js
    assert "Secure" in js
    assert "expires=Thu, 01 Jan 1970" in js                 # delete: 과거 expires
    assert "Domain" not in js                               # Domain 미지정
    assert "localStorage" not in js and "sessionStorage" not in js
    assert PASSWORD not in js and SECRET not in js


def test_render_passes_completion_callback_and_key():
    cb = lambda: None
    fake = _FakeComponent()
    a.render_cookie_set(a.issue_token(_key()), on_completed=cb, component=fake)
    a.render_cookie_delete(on_completed=cb, component=fake)
    assert all(c["on_completed_change"] is cb for c in fake.calls)
    assert fake.calls[0]["key"] == "auth_cookie_set"
    assert fake.calls[1]["key"] == "auth_cookie_delete"


def test_render_cookie_set_failure_is_silent():
    """mount 실패 시 예외 전파 없음 — 세션 로그인 유지(30일 유지만 미동작)."""
    assert a.render_cookie_set(a.issue_token(_key()),
                               component=_FakeComponent(raise_on_call=True)) is None
    assert a.render_cookie_delete(component=_FakeComponent(raise_on_call=True)) is None


def test_render_cookie_set_rejects_untrusted_token_without_leaking_it():
    bad = "x'; alert(1);//"
    with pytest.raises(ValueError) as ei:
        a.render_cookie_set(bad, component=_FakeComponent())
    assert bad not in str(ei.value)                         # 원본 token 비노출


# ── gate 로그아웃 2단계 흐름 (dashboard/app.py) ─────────────
def test_begin_logout_sets_pending_without_rerun():
    """1단계: 인증 해제 + 삭제 pending 기록만 — st.rerun 호출 0(stub에 rerun 없음)."""
    m = _dash_stubbed()
    m.st.session_state["authed"] = True
    m.st.session_state[m._AUTH_COOKIE_PENDING] = "tok"
    m._begin_logout()
    s = m.st.session_state
    assert s["authed"] is False
    assert s[m._AUTH_LOGGED_OUT] is True
    assert s[m._AUTH_COOKIE_DELETE_PENDING] is True
    assert m._AUTH_COOKIE_PENDING not in s                  # 발급 대기 토큰 폐기


def test_delete_completion_callback_idempotent_and_no_rerun():
    m = _dash_stubbed()
    m.st.session_state[m._AUTH_COOKIE_DELETE_PENDING] = True
    m._on_cookie_delete_done()
    m._on_cookie_delete_done()                              # 중복 수신에도 안전
    s = m.st.session_state
    assert m._AUTH_COOKIE_DELETE_PENDING not in s
    assert s[m._AUTH_COOKIE_DELETE_DONE] is True


def test_set_completion_callback_idempotent_and_no_rerun():
    m = _dash_stubbed()
    m.st.session_state[m._AUTH_COOKIE_PENDING] = "tok"
    m._on_cookie_set_done()
    m._on_cookie_set_done()
    assert m._AUTH_COOKIE_PENDING not in m.st.session_state


def test_auth_flow_functions_never_call_st_rerun():
    """rerun은 위젯/완료 이벤트의 자연 rerun만 사용 — 명시적 st.rerun() 호출 0회.
    (docstring·주석이 아니라 실제 호출 노드를 AST로 검사한다.)"""
    import ast
    import textwrap
    m = _dash()
    for fn in (m.gate, m._begin_logout, m._try_login,
               m._on_cookie_set_done, m._on_cookie_delete_done):
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr != "rerun", fn.__name__


def test_try_login_success_sets_session_and_pending_token():
    m = _dash_stubbed()
    m.st.session_state["auth_pw"] = "pw123"
    m.st.session_state[m._AUTH_LOGGED_OUT] = True
    m.st.session_state[m._AUTH_COOKIE_DELETE_DONE] = True
    m._try_login()
    s = m.st.session_state
    assert s["authed"] is True
    assert m._AUTH_LOGGED_OUT not in s                      # 재로그인 시 차단 해제
    assert m._AUTH_COOKIE_DELETE_DONE not in s
    tok = s[m._AUTH_COOKIE_PENDING]
    assert m.auths.verify_token(m.auths.derive_key(SECRET, "pw123"), tok)
    assert "pw123" not in tok


def test_try_login_wrong_password_rejected():
    m = _dash_stubbed()
    m.st.session_state["auth_pw"] = "wrong"
    m._try_login()
    s = m.st.session_state
    assert not s.get("authed")
    assert s[m._AUTH_LOGIN_FAILED] is True
    assert m._AUTH_COOKIE_PENDING not in s


def test_try_login_without_secret_falls_back_to_session_only():
    """secret 미설정 → 토큰 발급 없이 세션 로그인만(crash 없음)."""
    m = _dash_stubbed()
    m.config = SimpleNamespace(APP_PASSWORD="pw123", APP_SESSION_SECRET="")
    m.st.session_state["auth_pw"] = "pw123"
    m._try_login()
    assert m.st.session_state["authed"] is True
    assert m._AUTH_COOKIE_PENDING not in m.st.session_state


def test_should_clear_login_cookie_decision():
    """무효·로그아웃 cookie만 삭제 대상 — cookie 없으면 항상 False."""
    m = _dash()
    f = m._should_clear_login_cookie
    assert f("tok", False, False, b"key")                   # 무효 cookie(검증 실패 후)
    assert f("tok", True, False, None)                      # 로그아웃 삭제 대기
    assert f("tok", False, True, None)                      # 로그아웃 세션
    assert not f(None, True, True, b"key")                  # cookie 없음
    assert not f("", False, False, b"key")
    assert not f("tok", False, False, None)                 # 키 없음 + 정상 상태
