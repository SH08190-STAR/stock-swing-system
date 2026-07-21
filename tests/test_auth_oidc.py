"""
tests/test_auth_oidc.py — AUTH_MODE 전환 + Google OIDC gate 검증.

app.auth 순수 함수(모드 판정·이메일 allowlist)와 dashboard gate 흐름을
stub streamlit으로 검사한다. 실제 네트워크·DB·Google 호출 없음.
실제 이메일·client ID·secret은 사용하지 않는다(더미 @example.com만).
"""
import ast
import importlib.util
import inspect
import os
import textwrap
from types import SimpleNamespace

from app import auth

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _dash():
    p = os.path.join(ROOT, "dashboard", "app.py")
    spec = importlib.util.spec_from_file_location("dash_for_oidc_test", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ── A. 인증 모드 판정 ───────────────────────────────────────
def test_mode_unset_is_password():
    assert auth.resolve_auth_mode("") == "password"
    assert auth.resolve_auth_mode(None) == "password"


def test_mode_password_explicit():
    assert auth.resolve_auth_mode("password") == "password"


def test_mode_oidc():
    assert auth.resolve_auth_mode("oidc") == "oidc"


def test_mode_unknown_fails_closed():
    assert auth.resolve_auth_mode("google") == "invalid"
    assert auth.resolve_auth_mode("both") == "invalid"
    assert auth.resolve_auth_mode(123) == "invalid"


def test_mode_case_and_whitespace_normalized():
    assert auth.resolve_auth_mode("  OIDC  ") == "oidc"
    assert auth.resolve_auth_mode("Password") == "password"
    assert auth.resolve_auth_mode("   ") == "password"      # 공백만 = 미설정과 동일


# ── B. 이메일 allowlist ─────────────────────────────────────
ALLOW = "allowed@example.com"


def test_exact_email_allowed():
    assert auth.is_email_allowed("allowed@example.com", ALLOW) is True


def test_email_case_insensitive():
    assert auth.is_email_allowed("Allowed@Example.COM", ALLOW) is True


def test_email_whitespace_normalized():
    assert auth.is_email_allowed("  allowed@example.com \n", ALLOW) is True
    assert auth.is_email_allowed("allowed@example.com", "  allowed@example.com  ") is True


def test_unlisted_email_denied():
    assert auth.is_email_allowed("other@example.com", ALLOW) is False


def test_missing_email_denied():
    assert auth.is_email_allowed(None, ALLOW) is False
    assert auth.is_email_allowed("", ALLOW) is False
    assert auth.is_email_allowed("   ", ALLOW) is False


def test_missing_allowlist_fails_closed():
    assert auth.is_email_allowed("allowed@example.com", None) is False
    assert auth.is_email_allowed("allowed@example.com", "") is False


def test_empty_allowlist_fails_closed():
    assert auth.is_email_allowed("allowed@example.com", []) is False
    assert auth.is_email_allowed("allowed@example.com", " , , ") is False


def test_partial_match_denied():
    assert auth.is_email_allowed("allowed", ALLOW) is False
    assert auth.is_email_allowed("allowed@example", ALLOW) is False
    assert auth.is_email_allowed("xallowed@example.com", ALLOW) is False
    assert auth.is_email_allowed("allowed@example.com.evil.com", ALLOW) is False


def test_same_domain_other_email_denied():
    assert auth.is_email_allowed("intruder@example.com", ALLOW) is False


def test_allowlist_accepts_list_and_csv():
    assert auth.is_email_allowed("b@example.com", "a@example.com, b@example.com") is True
    assert auth.is_email_allowed("b@example.com", ["a@example.com", "B@Example.com"]) is True
    assert auth.parse_allowed_emails(", ,a@example.com ,") == ["a@example.com"]
    assert auth.parse_allowed_emails(123) == []


# ── C. OIDC gate 흐름 (stub streamlit) ──────────────────────
# [auth] preflight 통과용 유효 더미 설정 — 실제 값 아님(전부 example 도메인).
VALID_AUTH_SECTION = {
    "redirect_uri": "https://app.example.com/oauth2callback",
    "cookie_secret": "0123456789abcdef0123456789abcdef",   # 32바이트 더미
    "client_id": "dummy-client-id",
    "client_secret": "dummy-client-secret",
    "server_metadata_url": "https://idp.example.com/.well-known/openid-configuration",
}


class _Sidebar:
    def __init__(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _OidcStubSt:
    """OIDC gate가 쓰는 최소 streamlit 표면. login/logout/버튼 배선을 기록한다."""

    def __init__(self, user=None, secrets=None):
        self.session_state = {}
        self.user = user
        self.secrets = {"auth": dict(VALID_AUTH_SECTION)} if secrets is None else secrets
        self.errors = []
        self.captions = []
        self.buttons = []           # (label, on_click)
        self.button_keys = []       # 렌더된 버튼의 key (None 포함)
        self.clicks = set()         # 클릭 시뮬레이션: label 또는 key를 넣으면
                                    # 다음 렌더에서 해당 버튼이 True를 반환한다
        self.rerun_calls = 0
        self.stop_calls = 0
        self.login_calls = 0
        self.logout_calls = 0
        self.sidebar = _Sidebar()

    def stop(self):
        self.stop_calls += 1

    def login(self, provider=None):
        self.login_calls += 1

    def logout(self):
        self.logout_calls += 1

    def title(self, *a, **k):
        pass

    def caption(self, msg, *a, **k):
        self.captions.append(str(msg))

    def error(self, msg):
        self.errors.append(str(msg))

    def button(self, label, *a, on_click=None, key=None, **k):
        self.buttons.append((label, on_click))
        self.button_keys.append(key)
        # 실제 Streamlit처럼 클릭된 run에서만 True — if 방식 배선을 실행 검증한다
        return (label in self.clicks) or (key is not None and key in self.clicks)

    def rerun(self):
        self.rerun_calls += 1

    def text_input(self, *a, **k):
        raise AssertionError("OIDC 모드에서 비밀번호 UI가 호출됨")


class _Boom:
    """접근 즉시 실패하는 sentinel — 미로그인·미허용 시 DB/Relay 모듈 무접촉 증명."""

    def __getattr__(self, name):
        raise AssertionError(f"차단 상태에서 보호 자원 접근: {name}")


def _stub_oidc(user=None, allowed=ALLOW, config_extra=None, secrets=None):
    m = _dash()
    m.st = _OidcStubSt(user, secrets=secrets)
    cfg = {"AUTH_MODE": "oidc", "ALLOWED_GOOGLE_EMAILS": allowed}
    cfg.update(config_extra or {})
    m.config = SimpleNamespace(**cfg)
    return m


def _user(email="allowed@example.com", name="tester", logged_in=True):
    return SimpleNamespace(is_logged_in=logged_in, email=email, name=name)


def test_logged_out_shows_login_button_and_blocks():
    m = _stub_oidc(user=None)
    assert m.gate() is False
    labels = [b[0] for b in m.st.buttons]
    assert any("Google" in l for l in labels)
    # 버튼 on_click이 st.login에 직접 배선 — 눌렀을 때만 login 호출
    login_btn = next(b for b in m.st.buttons if "Google" in b[0])
    assert m.st.login_calls == 0
    login_btn[1]()
    assert m.st.login_calls == 1


def test_logged_out_via_is_logged_in_false():
    m = _stub_oidc(user=_user(logged_in=False))
    assert m.gate() is False
    assert any("Google" in b[0] for b in m.st.buttons)


def test_allowed_user_passes():
    m = _stub_oidc(user=_user())
    assert m.gate() is True
    assert m.st.errors == []


def test_allowed_user_gets_logout_button():
    m = _stub_oidc(user=_user())
    assert m.gate() is True                       # 클릭 전 본문 통과 정상
    assert any("로그아웃" in b[0] for b in m.st.buttons)
    assert m.st.logout_calls == 0                 # 렌더만으로는 st.logout 호출 0


def test_logout_click_executes_st_logout_once_without_rerun():
    """클릭된 run에서 실제 st.logout이 정확히 1회 실행되고 추가 rerun이 없다.

    배선 참조 검사(on_click == st.logout)가 아니라 클릭 시뮬레이션으로
    실행 경로 자체를 검증한다 — 괄호 누락(st.logout 참조만)·lambda 반환·
    잘못된 wrapper 결함은 이 테스트에서 logout_calls == 0으로 잡힌다."""
    m = _stub_oidc(user=_user())
    m.st.clicks.add("oidc_logout")
    m.gate()
    assert m.st.logout_calls == 1
    assert m.st.rerun_calls == 0                  # st.logout 뒤 추가 rerun 금지
    assert m.st.stop_calls == 0


def test_denied_user_blocked_with_message():
    m = _stub_oidc(user=_user(email="other@example.com"))
    assert m.gate() is False
    assert any("허용되지 않은" in e for e in m.st.errors)
    assert m.st.logout_calls == 0                 # 렌더만으로는 호출 0
    # 계정 변경 경로: 클릭 시 실제 st.logout 1회
    m2 = _stub_oidc(user=_user(email="other@example.com"))
    m2.st.clicks.add("oidc_switch_account")
    assert m2.gate() is False
    assert m2.st.logout_calls == 1
    assert m2.st.rerun_calls == 0


def test_missing_email_claim_blocked():
    m = _stub_oidc(user=_user(email=None))
    assert m.gate() is False
    assert any("허용되지 않은" in e for e in m.st.errors)


def test_missing_allowlist_blocks_even_logged_in():
    m = _stub_oidc(user=_user(), allowed="")
    assert m.gate() is False


def test_invalid_mode_fails_closed_without_any_login_ui():
    m = _stub_oidc(user=_user(), config_extra={"AUTH_MODE": "weird"})
    assert m.gate() is False
    assert m.st.buttons == []                     # 로그인 버튼조차 없음
    assert any("관리자 설정 오류" in e for e in m.st.errors)


def test_oidc_mode_never_reads_app_password():
    class _NoPwConfig:
        AUTH_MODE = "oidc"
        ALLOWED_GOOGLE_EMAILS = ALLOW

        @property
        def APP_PASSWORD(self):
            raise AssertionError("OIDC 모드에서 APP_PASSWORD 접근")

    m = _dash()
    m.st = _OidcStubSt(_user())
    m.config = _NoPwConfig()
    assert m.gate() is True
    m2 = _dash()
    m2.st = _OidcStubSt(None)
    m2.config = _NoPwConfig()
    assert m2.gate() is False


def test_oidc_gate_has_no_rerun():
    m = _stub_oidc(user=_user())
    m.gate()
    assert m.st.rerun_calls == 0
    tree = ast.parse(textwrap.dedent(inspect.getsource(m._oidc_gate)))
    assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                   and n.func.attr == "rerun" for n in ast.walk(tree))


def test_st_logout_only_appears_as_direct_call():
    """_oidc_gate 안의 st.logout은 반드시 직접 호출(st.logout())로만 존재한다.

    이 저장소의 계약: Production Community Cloud에서 on_click 배선이 실제로
    무반응이었으므로(내부 원인 미확정) 본문 직접 호출 형태만 허용한다.
    Streamlit 일반의 on_click 사용 가부에 대한 주장이 아니다.
    괄호 누락(if btn: st.logout)·콜백 참조·lambda·wrapper 반환을 AST로 차단."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(_dash()._oidc_gate)))
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    seen = 0
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and node.attr == "logout"
                and isinstance(node.value, ast.Name) and node.value.id == "st"):
            seen += 1
            p = parents.get(node)
            assert isinstance(p, ast.Call) and p.func is node, \
                "st.logout이 호출되지 않고 참조만 됨(괄호 누락/콜백/lambda)"
    assert seen >= 2                        # 사이드바 + 미허용 화면 두 경로 모두
    assert not any(isinstance(n, ast.Lambda) for n in ast.walk(tree))


def test_oidc_widget_keys_present_and_unique():
    m = _stub_oidc(user=_user())
    m.gate()
    keys = [k for k in m.st.button_keys if k is not None]
    assert "oidc_logout" in keys
    assert len(keys) == len(set(keys))      # 동일 key 충돌 없음


def test_password_mode_renders_no_oidc_logout_button():
    class _PwUiStub(_OidcStubSt):
        def text_input(self, *a, **k):
            return ""

    m = _dash()
    m.st = _PwUiStub(None, secrets={})
    m.config = SimpleNamespace(AUTH_MODE="password", APP_PASSWORD="pw123")
    assert m.gate() is False
    assert not any("로그아웃" in b[0] for b in m.st.buttons)
    assert m.st.logout_calls == 0


def test_oidc_gate_does_not_touch_session_state():
    """OIDC 경로에 session_state 인증 흉내·custom 저장이 재도입되지 않는다."""
    src = textwrap.dedent(inspect.getsource(_dash()._oidc_gate))
    assert "session_state" not in src
    m = _stub_oidc(user=_user())
    m.st.clicks.add("oidc_logout")
    m.gate()
    assert m.st.session_state == {}         # 클릭 후에도 세션 저장 0


def test_no_custom_cookie_or_component_in_dashboard():
    # 금지 문자열은 조합 생성 — 이 테스트 파일이 스캔에 걸리지 않게 한다.
    forbidden = [
        ".".join(("st", "context", "cookies")),
        ".".join(("document", "cookie")),
        "local" + "Storage",
        ".".join(("components", "v1")),
        ".".join(("components", "v2")),
        "_".join(("APP", "SESSION", "SECRET")),
    ]
    for rel in ("dashboard/app.py", "app/auth.py", "app/config.py"):
        with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
            src = f.read()
        for word in forbidden:
            assert word not in src, f"{word} in {rel}"


# ── D. 보호 경계 — 미로그인·미허용 시 DB/Relay 무접촉 ────────
def test_main_gate_runs_before_everything():
    m = _dash()
    tree = ast.parse(textwrap.dedent(inspect.getsource(m.main)))
    first = tree.body[0].body[0]
    assert isinstance(first, ast.If)
    assert isinstance(first.test, ast.UnaryOp) and isinstance(first.test.op, ast.Not)
    assert isinstance(first.test.operand, ast.Call)
    assert first.test.operand.func.id == "gate"
    assert any(isinstance(n, ast.Return) for n in first.body)


def _boom_protected(m):
    m.db = _Boom()
    m.qt = _Boom()
    m.wl = _Boom()
    m.tov = _Boom()
    m.load_data = _Boom().__getattr__  # 호출 시도 자체가 실패
    return m


def test_logged_out_touches_no_protected_modules():
    m = _boom_protected(_stub_oidc(user=None))
    assert m.main() is None                       # gate 차단 후 즉시 종료


def test_denied_touches_no_protected_modules():
    m = _boom_protected(_stub_oidc(user=_user(email="other@example.com")))
    assert m.main() is None


def test_invalid_mode_touches_no_protected_modules():
    m = _boom_protected(_stub_oidc(user=_user(), config_extra={"AUTH_MODE": "?"}))
    assert m.main() is None


# ── F. password 모드 fail closed (보안 하드닝) ───────────────
def _stub_password(config_ns):
    m = _dash()
    m.st = _OidcStubSt(None, secrets={})    # secrets 미구성 환경
    m.config = config_ns
    return m


def _assert_pw_fail_closed(m):
    assert m.gate() is False
    assert any("관리자 인증 설정 오류" in e for e in m.st.errors)
    assert m.st.stop_calls == 1
    assert m.st.buttons == []               # 입장 버튼·로그인 버튼 미노출


def test_password_missing_fails_closed():
    _assert_pw_fail_closed(_stub_password(SimpleNamespace(AUTH_MODE="password")))


def test_password_empty_fails_closed():
    _assert_pw_fail_closed(_stub_password(
        SimpleNamespace(AUTH_MODE="password", APP_PASSWORD="")))


def test_password_blank_fails_closed():
    _assert_pw_fail_closed(_stub_password(
        SimpleNamespace(AUTH_MODE="password", APP_PASSWORD="   ")))


def test_password_none_fails_closed():
    _assert_pw_fail_closed(_stub_password(
        SimpleNamespace(AUTH_MODE="password", APP_PASSWORD=None)))


def test_mode_unset_and_no_password_fails_closed():
    _assert_pw_fail_closed(_stub_password(SimpleNamespace()))


def test_password_fail_closed_touches_no_protected_modules():
    m = _boom_protected(_stub_password(SimpleNamespace(AUTH_MODE="password")))
    assert m.main() is None                 # DB·Relay·본문 접근 0


# ── G. 설정 리더 — st.secrets > env > 기본값 ─────────────────
def test_secrets_priority_over_env():
    v = auth.read_setting("AUTH_MODE", secrets={"AUTH_MODE": "oidc"},
                          env={"AUTH_MODE": "password"})
    assert v == "oidc"


def test_env_fallback_when_secret_absent():
    assert auth.read_setting("X", secrets={}, env={"X": "from-env"}) == "from-env"
    assert auth.read_setting("X", secrets=None, env={"X": "from-env"}) == "from-env"


def test_blank_values_fall_through_to_default():
    assert auth.read_setting("X", secrets={"X": "  "}, env={"X": ""},
                             default="dflt") == "dflt"


def test_secrets_list_value_passthrough():
    v = auth.read_setting("ALLOWED_GOOGLE_EMAILS",
                          secrets={"ALLOWED_GOOGLE_EMAILS": ["a@example.com"]},
                          env={})
    assert v == ["a@example.com"]


def test_allowlist_dedup_and_cleanup():
    got = auth.parse_allowed_emails(" a@example.com, A@Example.COM ,, b@example.com ")
    assert got == ["a@example.com", "b@example.com"]
    assert auth.parse_allowed_emails(["a@example.com", " a@example.com "]) == ["a@example.com"]


def test_gate_uses_secrets_before_config():
    """secrets의 AUTH_MODE·allowlist가 config(env 기반)보다 우선한다."""
    secrets = {"AUTH_MODE": "oidc", "ALLOWED_GOOGLE_EMAILS": "allowed@example.com",
               "auth": dict(VALID_AUTH_SECTION)}
    m = _stub_oidc(user=_user(), config_extra={"AUTH_MODE": "password",
                                               "APP_PASSWORD": "pw123",
                                               "ALLOWED_GOOGLE_EMAILS": ""},
                   secrets=secrets)
    assert m.gate() is True                 # password 모드가 아닌 oidc로 동작


# ── H. OIDC [auth] preflight ────────────────────────────────
def _auth_sec(**over):
    d = dict(VALID_AUTH_SECTION)
    d.update(over)
    for k, v in list(d.items()):
        if v is _DEL:
            del d[k]
    return d


_DEL = object()


def test_preflight_valid_section_ok():
    assert auth.oidc_config_ok(VALID_AUTH_SECTION) is True


def test_preflight_no_section_fails():
    assert auth.oidc_config_ok(None) is False


def test_preflight_each_required_key_missing_fails():
    for key in auth.OIDC_REQUIRED_KEYS:
        assert auth.oidc_config_ok(_auth_sec(**{key: _DEL})) is False, key


def test_preflight_blank_value_fails():
    for key in auth.OIDC_REQUIRED_KEYS:
        assert auth.oidc_config_ok(_auth_sec(**{key: "   "})) is False, key
        assert auth.oidc_config_ok(_auth_sec(**{key: None})) is False, key


def test_preflight_relative_redirect_uri_rejected():
    assert auth.oidc_config_ok(_auth_sec(redirect_uri="/oauth2callback")) is False
    assert auth.oidc_config_ok(_auth_sec(redirect_uri="ftp://x/oauth2callback")) is False


def test_preflight_wrong_callback_path_rejected():
    assert auth.oidc_config_ok(_auth_sec(
        redirect_uri="https://app.example.com/callback")) is False


def test_preflight_short_cookie_secret_rejected():
    assert auth.oidc_config_ok(_auth_sec(cookie_secret="short")) is False
    assert auth.oidc_config_ok(_auth_sec(cookie_secret="x" * 31)) is False
    assert auth.oidc_config_ok(_auth_sec(cookie_secret="x" * 32)) is True


def test_oidc_gate_fail_closed_without_auth_section():
    m = _stub_oidc(user=_user(), secrets={})            # [auth] 없음
    assert m.gate() is False
    assert any("Google 로그인 설정 오류" in e for e in m.st.errors)
    assert m.st.stop_calls == 1
    assert m.st.buttons == []                           # 로그인 버튼 미노출
    assert m.st.login_calls == 0                        # st.login 호출 0


def test_oidc_gate_fail_closed_with_broken_auth_section():
    m = _stub_oidc(user=None,
                   secrets={"auth": _auth_sec(cookie_secret="short")})
    assert m.gate() is False
    assert m.st.buttons == [] and m.st.login_calls == 0


def test_oidc_config_error_touches_no_protected_modules():
    m = _boom_protected(_stub_oidc(user=_user(), secrets={}))
    assert m.main() is None


def test_oidc_valid_config_shows_login_button():
    m = _stub_oidc(user=None)                           # 유효 [auth] 기본 스텁
    assert m.gate() is False
    login_btn = next(b for b in m.st.buttons if "Google" in b[0])
    login_btn[1]()
    assert m.st.login_calls == 1                        # 정상 설정에서만 st.login 가능


# ── I. 렌더 회귀 — Streamlit magic bare expression 출력 금지 ─
# Streamlit magic은 메인 스크립트(함수 본문 포함)의 bare expression을
# st.write로 렌더한다. 과거 `"AUTH_MODE" in sec` 단독 라인이 화면 좌측 상단에
# `True`로 노출된 회귀를 막는다: (1) magic을 AST로 에뮬레이트해 실제 렌더
# 문자열을 수집·검증하고, (2) 소스에 bare expression 자체가 없음을 보장한다.
class _RenderSt(_OidcStubSt):
    """모든 렌더 호출(write/text/markdown/title/caption/error)을 문자열로 수집."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.rendered = []

    def write(self, *args, **k):
        self.rendered.extend(str(a) for a in args)

    def text(self, body, *a, **k):
        self.rendered.append(str(body))

    def markdown(self, body, *a, **k):
        self.rendered.append(str(body))

    def title(self, body, *a, **k):
        self.rendered.append(str(body))

    def caption(self, msg, *a, **k):
        self.captions.append(str(msg))
        self.rendered.append(str(msg))

    def error(self, msg):
        self.errors.append(str(msg))
        self.rendered.append(str(msg))


class _MagicEmulator(ast.NodeTransformer):
    """Streamlit magic 근사 — bare expression(호출·docstring 제외)을 st.write로
    감싼다. 실제 magic이 값으로 렌더하는 부류만 재현한다."""

    def generic_visit(self, node):
        super().generic_visit(node)
        for field in ("body", "orelse", "finalbody"):
            stmts = getattr(node, field, None)
            if isinstance(stmts, list):
                setattr(node, field, self._rewrite(stmts))
        return node

    @staticmethod
    def _rewrite(stmts):
        out = []
        for i, stmt in enumerate(stmts):
            if (isinstance(stmt, ast.Expr)
                    and not isinstance(stmt.value, (ast.Call, ast.Await))
                    and not (i == 0 and isinstance(stmt.value, ast.Constant)
                             and isinstance(stmt.value.value, str))):
                wrapped = ast.Expr(ast.Call(
                    func=ast.Attribute(value=ast.Name(id="st", ctx=ast.Load()),
                                       attr="write", ctx=ast.Load()),
                    args=[stmt.value], keywords=[]))
                out.append(ast.copy_location(wrapped, stmt))
            else:
                out.append(stmt)
        return out


def _dash_magic(user=None, secrets=None, config_extra=None):
    """dashboard/app.py를 magic 에뮬레이션 AST로 로드 — 렌더 회귀 검증용."""
    p = os.path.join(ROOT, "dashboard", "app.py")
    with open(p, encoding="utf-8") as f:
        tree = _MagicEmulator().visit(ast.parse(f.read()))
    ast.fix_missing_locations(tree)
    spec = importlib.util.spec_from_file_location("dash_magic_test", p)
    m = importlib.util.module_from_spec(spec)
    exec(compile(tree, p, "exec"), m.__dict__)
    m.st = _RenderSt(user, secrets=secrets)
    cfg = {"AUTH_MODE": "oidc", "ALLOWED_GOOGLE_EMAILS": ALLOW}
    cfg.update(config_extra or {})
    m.config = SimpleNamespace(**cfg)
    return m


def _assert_no_bool_rendered(m):
    assert "True" not in m.st.rendered
    assert "False" not in m.st.rendered


def test_oidc_login_screen_renders_no_bool_text():
    m = _dash_magic(user=None)
    assert m.gate() is False
    assert any("허용된 Google 계정" in c for c in m.st.captions)   # 안내 유지
    assert any("Google" in b[0] for b in m.st.buttons)             # 버튼 유지
    _assert_no_bool_rendered(m)


def test_oidc_other_screens_render_no_bool_text():
    for user in (_user(), _user(email="other@example.com"),
                 _user(logged_in=False)):
        m = _dash_magic(user=user)
        m.gate()
        _assert_no_bool_rendered(m)


def test_password_screen_renders_no_bool_text():
    m = _dash_magic(user=None, secrets={},
                    config_extra={"AUTH_MODE": "password", "APP_PASSWORD": "pw123"})
    m.st.text_input = lambda *a, **k: ""
    assert m.gate() is False
    _assert_no_bool_rendered(m)


def test_fail_closed_screen_renders_no_bool_text():
    m = _dash_magic(user=None, secrets={}, config_extra={"AUTH_MODE": "weird"})
    assert m.gate() is False
    assert any("관리자 설정 오류" in e for e in m.st.errors)       # 오류 화면 유지
    _assert_no_bool_rendered(m)


def test_no_bare_expressions_in_dashboard_source():
    """메인 스크립트의 bare expression은 magic이 그대로 렌더한다 — 0건 유지."""
    p = os.path.join(ROOT, "dashboard", "app.py")
    with open(p, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    offenders = []
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            stmts = getattr(node, field, None)
            if not isinstance(stmts, list):
                continue
            for i, stmt in enumerate(stmts):
                if not isinstance(stmt, ast.Expr):
                    continue
                if isinstance(stmt.value, (ast.Call, ast.Await)):
                    continue
                if (i == 0 and isinstance(stmt.value, ast.Constant)
                        and isinstance(stmt.value.value, str)):
                    continue                      # docstring
                offenders.append(stmt.lineno)
    assert offenders == [], f"bare expression lines: {offenders}"


def test_no_debug_write_or_print_in_auth_flow():
    m = _dash()
    for fn in (m.gate, m._oidc_gate, m._password_gate,
               m._secrets_or_none, m._auth_fail_closed):
        src = inspect.getsource(fn)
        assert "st.write" not in src, fn.__name__
        assert "print(" not in src, fn.__name__


# ── E. password 모드 불변 (기존 test_auth_gate.py 보완) ──────
def test_password_mode_explicit_uses_password_gate():
    m = _dash()

    class _PwStub(_OidcStubSt):
        def text_input(self, *a, **k):
            return "pw123"

        def button(self, label, *a, on_click=None, key=None, **k):
            self.buttons.append((label, on_click))
            return True

    m.st = _PwStub()
    m.config = SimpleNamespace(AUTH_MODE="password", APP_PASSWORD="pw123")
    m.gate()
    assert m.st.session_state.get("authed") is True
    assert m.st.rerun_calls == 1
    assert m.st.login_calls == 0 and m.st.logout_calls == 0
