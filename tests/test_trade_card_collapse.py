"""
tests/test_trade_card_collapse.py — 매매 카드 접힘형 목록(record id 기반 펼침 상태) 검증.
streamlit 세션은 stub으로 대체 — 실제 Supabase/네트워크/DB 접근 없음.
"""
import os
import importlib.util
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _dash():
    p = os.path.join(ROOT, "dashboard", "app.py")
    spec = importlib.util.spec_from_file_location("dash_for_card_test", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _with_fake_state(m):
    """모듈 전역 st를 세션 stub으로 교체(순수 상태 로직만 검사)."""
    m.st = SimpleNamespace(session_state={})
    return m


# ── 펼침 상태: record id 기반 set ────────────────────────────
def test_initially_all_collapsed():
    m = _with_fake_state(_dash())
    assert m._expanded_ids() == set()                       # 최초 진입 — 전부 접힘
    assert "uuid-1" not in m._expanded_ids()


def test_toggle_open_and_close_single_card():
    m = _with_fake_state(_dash())
    m._toggle_trade_card("uuid-1")
    assert m._expanded_ids() == {"uuid-1"}
    m._toggle_trade_card("uuid-1")                          # 같은 카드 재클릭 → 접힘
    assert m._expanded_ids() == set()


def test_multiple_cards_open_simultaneously():
    m = _with_fake_state(_dash())
    m._toggle_trade_card("uuid-1")
    m._toggle_trade_card("uuid-2")
    m._toggle_trade_card("uuid-3")
    assert m._expanded_ids() == {"uuid-1", "uuid-2", "uuid-3"}
    m._toggle_trade_card("uuid-2")                          # 하나 닫아도 나머지 유지
    assert m._expanded_ids() == {"uuid-1", "uuid-3"}


def test_state_survives_reorder_and_is_id_based():
    m = _with_fake_state(_dash())
    m._toggle_trade_card("uuid-b")
    records = [{"id": "uuid-a"}, {"id": "uuid-b"}, {"id": "uuid-c"}]
    open_before = [r["id"] for r in records if str(r["id"]) in m._expanded_ids()]
    records.reverse()                                       # 데이터 순서 변경
    open_after = [r["id"] for r in records if str(r["id"]) in m._expanded_ids()]
    assert open_before == ["uuid-b"] and open_after == ["uuid-b"]


def test_deleted_record_state_cleaned_and_new_record_collapsed():
    m = _with_fake_state(_dash())
    m._toggle_trade_card("uuid-old")
    m._expanded_ids().discard("uuid-old")                   # 삭제 핸들러와 동일 경로
    assert m._expanded_ids() == set()
    assert "uuid-new" not in m._expanded_ids()              # 새 record 기본 접힘


def test_expanded_state_persists_across_reruns():
    m = _with_fake_state(_dash())
    m._toggle_trade_card("uuid-1")
    # rerun 시뮬레이션: session_state는 유지되고 스크립트만 재실행된다
    assert m._expanded_ids() == {"uuid-1"}
    assert m._expanded_ids() == {"uuid-1"}


def test_expanded_key_namespace():
    m = _with_fake_state(_dash())
    m._toggle_trade_card("uuid-1")
    keys = set(m.st.session_state.keys())
    assert keys == {"trade_expanded_record_ids"}            # 가격·인증 key와 충돌 없음


def test_corrupted_state_resets_to_empty_set():
    m = _with_fake_state(_dash())
    m.st.session_state["trade_expanded_record_ids"] = "broken"
    assert m._expanded_ids() == set()


# ── 요약행 라벨 ─────────────────────────────────────────────
def test_summary_label_with_etf():
    m = _dash()
    r = {"symbol": "NVO", "record_date": "2026-07-04", "status": "tp_in",
         "market_group": "US", "leverage_symbol": "NVOX"}
    lbl = m.trade_summary_label(r)
    assert "**NVO**" in lbl                                 # ticker 강조
    assert "2026\\-07\\-04" in lbl or "2026-07-04" in lbl   # 날짜(escape 허용)
    assert "TP IN" in lbl and ":orange[" in lbl             # 상태 + 앰버 계열
    assert "미장" in lbl
    assert "2× NVOX" in lbl                                 # ETF 있음 → 2× 표기
    assert lbl.rstrip().endswith("▾")                       # 접힘 chevron


def test_summary_label_without_etf_shows_base_stock():
    m = _dash()
    r = {"symbol": "005490", "record_date": "2026-07-01", "status": "waiting",
         "market_group": "KR", "leverage_symbol": None}
    lbl = m.trade_summary_label(r)
    assert "본주" in lbl and "2×" not in lbl
    assert "국장" in lbl
    assert "대기중" in lbl and ":gray[" in lbl


def test_summary_label_status_color_mapping_complete():
    m = _dash()
    expect = {"waiting": "gray", "entered": "blue", "tp_in": "orange", "completed": "green"}
    assert m._ST_MD_COLOR == expect
    for status, color in expect.items():
        r = {"symbol": "T", "record_date": "2026-01-01", "status": status,
             "market_group": "US", "leverage_symbol": ""}
        assert f":{color}[" in m.trade_summary_label(r)


def test_summary_label_chevron_reflects_expanded():
    m = _dash()
    r = {"symbol": "NVO", "record_date": "2026-07-04", "status": "entered",
         "market_group": "US", "leverage_symbol": ""}
    assert m.trade_summary_label(r, expanded=False).rstrip().endswith("▾")
    assert m.trade_summary_label(r, expanded=True).rstrip().endswith("▴")


def test_summary_label_escapes_markdown_and_katex():
    m = _dash()
    r = {"symbol": "A$B*[x]:red", "record_date": "2026-07-04", "status": "entered",
         "market_group": "US", "leverage_symbol": "E_F"}
    lbl = m.trade_summary_label(r)
    assert "\\$" in lbl and "\\*" in lbl and "\\[" in lbl   # $·서식 문자 무력화
    assert "A$B" not in lbl                                 # 원문 $ 그대로 남지 않음
    assert "E\\_F" in lbl


def test_summary_label_unknown_status_safe():
    m = _dash()
    r = {"symbol": "T", "record_date": "2026-01-01", "status": "weird",
         "market_group": "US", "leverage_symbol": ""}
    lbl = m.trade_summary_label(r)
    assert ":gray[weird]" in lbl                            # 미지 상태 → 중립색, 누락 없음
