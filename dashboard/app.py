"""
app.py — Z PICK 한국주식 워치리스트 대시보드 (Streamlit)

메뉴(요구 9종)
 1 전체 워치리스트   2 단기스윙종목     3 기존 섹터별
 4 오늘 신규 편입    5 오늘 분류 이탈   6 거래대금 순위
 7 변경 이력        8 확인 보류        9 마지막 최신화 시각(상단 고정)

기능: 종목명/코드 검색, 거래대금순 정렬, 섹터 필터, KOSPI/KOSDAQ 필터,
      신규 편입만 보기, CSV 다운로드, 모바일 대응, 간이 비밀번호 보호.

데이터는 Supabase에서 읽기만 한다(수집은 update.py가 담당).
"""
from __future__ import annotations
import sys
import os

# 이 파일명(dashboard/app.py)이 최상위 'app' 패키지와 이름이 같아,
# Streamlit이 dashboard/ 폴더를 경로 맨 앞에 두면 `import app`이 이 파일 자신을
# 가리켜 순환참조가 난다. 프로젝트 루트를 경로 맨 앞에 두고, 스크립트 폴더는
# import 경로에서 제외해 항상 진짜 app 패키지를 import하도록 보정한다.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
sys.path[:] = [p for p in sys.path if os.path.abspath(p) != _HERE]

import io
import datetime as dt
import pandas as pd
import streamlit as st

from app import config
from app import database as db
from app import watchlist as wl

st.set_page_config(page_title="Z PICK 워치리스트", page_icon="📊", layout="wide")


# ── 간이 비밀번호 보호 (APP_PASSWORD 설정 시) ───────────────
def gate() -> bool:
    if not config.APP_PASSWORD:
        return True
    if st.session_state.get("authed"):
        return True
    st.title("🔒 Z PICK")
    pw = st.text_input("접속 비밀번호", type="password")
    if st.button("입장"):
        if pw == config.APP_PASSWORD:
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("비밀번호가 올바르지 않습니다.")
    return False


def merge_universe(wl_rows: pd.DataFrame, db_stocks: pd.DataFrame) -> pd.DataFrame:
    """
    전체 워치리스트(해외 포함)에 DB의 한국주식 분류·수치를 덧입힌다.
    - 한국주식: DB의 classification(swing/sector/hold)과 거래대금 등을 사용.
    - 해외주식: 거래대금 분류 미적용 → classification="global"(원래 섹터 고정).
    워치리스트가 종목 universe의 단일 출처, DB는 한국 분류 결과의 출처.
    """
    if wl_rows is None or wl_rows.empty:
        return db_stocks
    base = wl_rows.rename(columns={"symbol": "code", "original_sector": "origin_sector"})
    keep = [c for c in ["code", "name", "country", "market", "origin_sector"] if c in base.columns]
    base = base[keep].copy()
    val_cols = ["code", "classification", "avg_6m", "short_avg", "today_value",
                "close", "change_pct", "used_days", "estimated", "data_date", "reason"]
    if db_stocks is not None and not db_stocks.empty:
        sel = db_stocks[[c for c in val_cols if c in db_stocks.columns]]
        merged = base.merge(sel, on="code", how="left")
    else:
        merged = base.copy()
        merged["classification"] = None
    # DB에 없는 종목: 해외=고정(global), 한국=아직 미수집(hold)
    is_kr = merged["country"] == "KR" if "country" in merged.columns else False
    na_cls = merged["classification"].isna()
    merged.loc[na_cls & ~is_kr, "classification"] = "global"
    merged.loc[na_cls & is_kr, "classification"] = "hold"
    return merged


@st.cache_data(ttl=600)
def load_data():
    db_stocks = pd.DataFrame(db.load_stocks())
    wl_rows = pd.DataFrame(wl.load_all())
    stocks = merge_universe(wl_rows, db_stocks)
    history = pd.DataFrame(db.load_history())
    last_update = db.get_meta("last_ok_update")
    last_date = db.get_meta("last_data_date")
    return stocks, history, last_update, last_date


def eok(v):
    """원 → 억원 문자열."""
    if pd.isna(v) or v is None:
        return "—"
    return f"{v/1e8:,.0f}억"


def csv_download(df: pd.DataFrame, label: str, fname: str):
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    st.download_button(label, buf.getvalue().encode("utf-8-sig"),
                       file_name=fname, mime="text/csv")


def main():
    if not gate():
        return

    stocks, history, last_update, last_date = load_data()

    # 상단: 요약 + 마지막 최신화 시각 (메뉴 9)
    c1, c2, c3, c4, c5 = st.columns(5)
    total_swing = int((stocks["classification"] == "swing").sum()) if len(stocks) else 0
    total_sector = int((stocks["classification"] == "sector").sum()) if len(stocks) else 0
    total_hold = int((stocks["classification"] == "hold").sum()) if len(stocks) else 0
    total_global = int((stocks["classification"] == "global").sum()) if len(stocks) else 0
    c1.metric("단기스윙", total_swing)
    c2.metric("기존 섹터(한국)", total_sector)
    c3.metric("확인 보류", total_hold)
    c4.metric("해외(고정)", total_global)
    c5.metric("데이터 기준일", last_date or "—")
    st.caption(f"🕒 마지막 최신화: {last_update or '아직 갱신 전'}  ·  대시보드는 읽기 전용 (갱신은 매 거래일 16:40 자동)")

    if len(stocks) == 0:
        st.info("아직 데이터가 없습니다. update.py가 한 번 실행되면 채워집니다.")
        return

    # 공통 필터 사이드바
    st.sidebar.header("필터")
    q = st.sidebar.text_input("종목명·코드 검색")
    country_opts = sorted([c for c in stocks.get("country", pd.Series(dtype=str)).dropna().unique() if c])
    country_sel = st.sidebar.multiselect("국가", country_opts, default=country_opts)
    market_opts = sorted([m for m in stocks["market"].dropna().unique() if m])
    markets = st.sidebar.multiselect("시장", market_opts, default=market_opts)
    sectors = sorted([s for s in stocks["origin_sector"].dropna().unique() if s])
    sec_sel = st.sidebar.multiselect("기존 섹터", sectors, default=sectors)
    sort_by_value = st.sidebar.checkbox("거래대금순 정렬", value=True)

    def apply_filters(df):
        d = df.copy()
        if q:
            ql = q.lower()
            d = d[d["name"].str.lower().str.contains(ql, na=False) |
                  d["code"].str.contains(q, na=False)]
        if country_sel and "country" in d.columns:
            d = d[d["country"].isin(country_sel)]
        if markets:
            d = d[d["market"].isin(markets)]
        if sec_sel:
            d = d[d["origin_sector"].isin(sec_sel) | d["origin_sector"].isna()]
        if sort_by_value and "avg_6m" in d.columns:
            d = d.sort_values("avg_6m", ascending=False, na_position="last")
        return d

    tabs = st.tabs([
        "전체", "단기스윙", "섹터 구성", "신규 편입",
        "분류 이탈", "거래대금 순위", "변경 이력", "확인 보류",
    ])

    # 현재 분류 섹터: swing → "단기스윙"(하나의 섹터로 모음), hold → "확인 보류",
    # 그 외(1,000억 초과)는 기존 섹터 유지. 워치리스트 원본(origin_sector)은 그대로 두고
    # 여기서 매 거래일 분류 결과로 현재 섹터만 산출한다(복귀 시 원래 섹터로 되돌리기 위함).
    def cur_cat_series(d):
        def f(row):
            c = row.get("classification")
            if c == "swing":
                return "단기스윙"
            if c == "hold":
                return "확인 보류"
            return row.get("origin_sector") or "(미분류)"
        return d.apply(f, axis=1)

    # 표시용 컬럼 정리
    def view(df):
        d = df.copy()
        d["현재섹터"] = cur_cat_series(d)
        if "classification" in d.columns:
            d["classification"] = d["classification"].map({
                "swing": "단기스윙", "sector": "기존섹터",
                "hold": "확인보류", "global": "해외(고정)",
            }).fillna(d["classification"])
        for col in ("avg_6m", "short_avg", "today_value"):
            if col in d.columns:
                d[col + "_억"] = d[col].apply(eok)
        show = ["name", "code", "country", "market", "현재섹터", "close", "change_pct",
                "today_value_억", "short_avg_억", "avg_6m_억",
                "origin_sector", "classification", "data_date"]
        show = [c for c in show if c in d.columns]
        ren = {"name":"종목명","code":"코드","country":"국가","market":"시장","close":"현재가",
               "change_pct":"전일대비%","today_value_억":"당일거래대금",
               "short_avg_억":"20일평균","avg_6m_억":"6개월평균",
               "origin_sector":"기존섹터","classification":"분류","data_date":"기준일"}
        return d[show].rename(columns=ren)

    # 1) 전체
    with tabs[0]:
        d = apply_filters(stocks)
        st.dataframe(view(d), use_container_width=True, hide_index=True)
        csv_download(d, "⬇ 전체 CSV", "zpick_all.csv")

    # 2) 단기스윙
    with tabs[1]:
        d = apply_filters(stocks[stocks["classification"] == "swing"])
        st.dataframe(view(d), use_container_width=True, hide_index=True)
        csv_download(d, "⬇ 단기스윙 CSV", "zpick_swing.csv")

    # 3) 섹터 구성 — "단기스윙"을 하나의 섹터로 맨 위에, 나머지는 기존 섹터별로
    with tabs[2]:
        d = apply_filters(stocks).copy()
        d["__cat"] = cur_cat_series(d)
        # 정렬: 단기스윙 먼저 → 기존 섹터(이름순) → 확인 보류 맨 뒤
        order_key = lambda c: (c != "단기스윙", c == "확인 보류", str(c))
        for cat in sorted(d["__cat"].dropna().unique(), key=order_key):
            sub = d[d["__cat"] == cat]
            label = "🔹 단기스윙 (1,000억 이하 · 섹터 통합)" if cat == "단기스윙" else cat
            st.subheader(f"{label} — {len(sub)}종목")
            st.dataframe(view(sub), use_container_width=True, hide_index=True)
        csv_download(d.drop(columns="__cat").assign(현재섹터=cur_cat_series(d)),
                     "⬇ 섹터구성 CSV (단기스윙 포함)", "zpick_categories.csv")

    # 4) 신규 편입 (오늘 history에서 swing 편입)
    with tabs[3]:
        if len(history):
            today = last_date
            ne = history[(history["change_date"] == today) &
                         (history["to_class"] == "단기스윙")]
            st.dataframe(ne, use_container_width=True, hide_index=True)
            if len(ne) == 0:
                st.info("오늘 신규 편입 종목이 없습니다.")
        else:
            st.info("이력이 아직 없습니다.")

    # 5) 분류 이탈 (오늘 섹터 복귀)
    with tabs[4]:
        if len(history):
            today = last_date
            ex = history[(history["change_date"] == today) &
                         (history["to_class"] == "기존섹터")]
            st.dataframe(ex, use_container_width=True, hide_index=True)
            if len(ex) == 0:
                st.info("오늘 분류 이탈 종목이 없습니다.")
        else:
            st.info("이력이 아직 없습니다.")

    # 6) 거래대금 순위
    with tabs[5]:
        d = stocks.dropna(subset=["avg_6m"]).sort_values("avg_6m", ascending=False)
        d = apply_filters(d)
        st.dataframe(view(d), use_container_width=True, hide_index=True)

    # 7) 변경 이력
    with tabs[6]:
        if len(history):
            h = history.copy()
            for col in ("prev_avg_6m", "new_avg_6m"):
                if col in h.columns:
                    h[col] = h[col].apply(eok)
            st.dataframe(h, use_container_width=True, hide_index=True)
            csv_download(history, "⬇ 이력 CSV", "zpick_history.csv")
        else:
            st.info("이력이 아직 없습니다.")

    # 8) 확인 보류
    with tabs[7]:
        d = stocks[stocks["classification"] == "hold"]
        cols = [c for c in ["name","code","market","origin_sector","reason","data_date"] if c in d.columns]
        st.dataframe(d[cols].rename(columns={
            "name":"종목명","code":"코드","market":"시장",
            "origin_sector":"기존섹터","reason":"사유","data_date":"기준일"}),
            use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
