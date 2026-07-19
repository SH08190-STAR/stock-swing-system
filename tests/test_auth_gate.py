"""
tests/test_auth_gate.py — 단순 비밀번호 gate(APP_PASSWORD + session_state) 검증.
30일 cookie 로그인 제거 후의 복원된 구조: 같은 세션 내 rerun에서는 로그인 유지,
새 세션에서는 재로그인. streamlit은 stub — 네트워크·DB 접근 없음.
"""
import ast
import importlib.util
import inspect
import os
import textwrap
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _dash():
    p = os.path.join(ROOT, "dashboard", "app.py")
    spec = importlib.util.spec_from_file_location("dash_for_gate_test", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class _StubSt:
    """gate()가 쓰는 최소 streamlit 표면. rerun 호출 횟수를 기록한다."""

    def __init__(self, pw_input="", button_clicked=False):
        self.session_state = {}
        self.errors = []
        self.rerun_calls = 0
        self.stop_calls = 0
        self.text_input_calls = 0
        self._pw = pw_input
        self._clicked = button_clicked

    def title(self, *a, **k):
        pass

    def stop(self):
        self.stop_calls += 1

    def text_input(self, *a, **k):
        self.text_input_calls += 1
        return self._pw

    def button(self, *a, **k):
        return self._clicked

    def error(self, msg):
        self.errors.append(str(msg))

    def rerun(self):
        self.rerun_calls += 1

    def toast(self, *a, **k):
        pass


def _stubbed(pw_input="", clicked=False, app_password="pw123"):
    m = _dash()
    m.st = _StubSt(pw_input, clicked)
    m.config = SimpleNamespace(APP_PASSWORD=app_password)
    return m


# ── 로그인 기본 ─────────────────────────────────────────────
def test_gate_fail_closed_when_no_password_configured():
    """APP_PASSWORD 미설정 자동 통과 제거(보안 하드닝) — fail closed.
    비밀번호 입력창도 열지 않고 관리자 오류만 표시 후 중단한다."""
    m = _stubbed(app_password="")
    assert m.gate() is False
    assert any("관리자 인증 설정 오류" in e for e in m.st.errors)
    assert m.st.stop_calls == 1
    assert m.st.text_input_calls == 0                       # 보호 UI 미노출


def test_login_with_correct_password():
    m = _stubbed(pw_input="pw123", clicked=True)
    m.gate()                                                # 클릭 run — 인증 기록 + rerun 1회
    assert m.st.session_state.get("authed") is True
    assert m.st.rerun_calls == 1
    assert m.st.errors == []
    assert m.gate() is True                                 # rerun 후 run — 통과


def test_login_with_wrong_password_rejected():
    m = _stubbed(pw_input="wrong", clicked=True)
    assert m.gate() is False
    assert m.st.session_state.get("authed") is not True
    assert any("올바르지" in e for e in m.st.errors)
    assert m.st.rerun_calls == 0


def test_authed_session_persists_across_reruns():
    """같은 세션 내 rerun(저장·가격 조회·탭 이동)에서는 session_state가 유지된다."""
    m = _stubbed()
    m.st.session_state["authed"] = True
    for _ in range(5):                                      # 연속 rerun 시뮬레이션
        assert m.gate() is True
    assert m.st.session_state["authed"] is True


def test_new_session_requires_login_again():
    """새 브라우저 세션 = 빈 session_state → 로그인 화면(복원 경로 없음)."""
    m = _stubbed(pw_input="", clicked=False)
    assert m.gate() is False
    assert "authed" not in m.st.session_state


# ── 저장·가격 조회가 인증을 건드리지 않는다 ─────────────────
def test_price_refresh_callback_keeps_auth_and_filters():
    """가격 새로고침 콜백은 가격 상태만 갱신 — 인증·위젯 key를 건드리지 않고
    st.rerun()도 직접 부르지 않는다(시장/상태 라디오 리셋 방지 수정 보존)."""
    m = _stubbed()
    m.st.session_state.update({"authed": True, "tr_mg": "미장", "tr_st": "TP IN"})
    m.clear_price_caches = lambda: None
    m._clear_ext_quotes = lambda: None
    m._refresh_prices()
    s = m.st.session_state
    assert s["authed"] is True
    assert s["tr_mg"] == "미장" and s["tr_st"] == "TP IN"
    assert "price_asof" in s
    assert m.st.rerun_calls == 0
    tree = ast.parse(textwrap.dedent(inspect.getsource(m._refresh_prices)))
    assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                   and n.func.attr == "rerun" for n in ast.walk(tree))


def test_card_toggle_does_not_touch_auth():
    m = _stubbed()
    m.st.session_state["authed"] = True
    m._toggle_trade_card("uuid-1")
    assert m.st.session_state["authed"] is True
    assert m._expanded_ids() == {"uuid-1"}


# ── 30일 로그인 잔재 0건 고정 ───────────────────────────────
def test_no_persistent_login_remnants_in_code():
    # 금지 문자열을 조합으로 생성 — 이 테스트 파일 자체가 잔재 스캔에 걸리지 않게 한다.
    forbidden = ["_".join(p) for p in (
        ("APP", "SESSION", "SECRET"), ("zpick", "session"), ("auth", "session"),
        ("zpick", "cookie", "action"), ("render", "cookie", "set"),
        ("render", "cookie", "delete"), ("logout", "pending"),
    )] + [".".join(("components", "v2", "component"))]
    for rel in ("dashboard/app.py", "app/config.py"):
        with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
            src = f.read()
        for word in forbidden:
            assert word not in src, f"{word} in {rel}"
    assert not os.path.exists(os.path.join(ROOT, "app", "_".join(("auth", "session")) + ".py"))
    assert not os.path.exists(os.path.join(ROOT, "tests", "test_" + "_".join(("auth", "session")) + ".py"))
