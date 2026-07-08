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
import html
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


def get_currency(row) -> str:
    """종목의 표시 통화 판별. 환율 변환은 하지 않는다(현지통화 그대로).
    한국(country=KR 또는 KOSPI/KOSDAQ/KONEX) → KRW, 그 외(NASDAQ/NYSE/AMEX 등) → USD."""
    country = str(row.get("country") or "").upper()
    market = str(row.get("market") or "").upper()
    if country in ("KR", "KOREA", "한국") or market in ("KOSPI", "KOSDAQ", "KONEX"):
        return "KRW"
    return "USD"


def format_price(value, currency: str) -> str:
    """가격 표시: KRW는 '78,000원'(소수 없음), USD는 '$195.74'(소수 2자리)."""
    if value is None or pd.isna(value):
        return "—"
    if currency == "KRW":
        return f"{float(value):,.0f}원"
    return f"${float(value):,.2f}"


def current_sector(row) -> str:
    """종목의 현재 섹터: swing→단기스윙, hold→확인 보류, 그 외→기존 섹터."""
    c = row.get("classification")
    if c == "swing":
        return "단기스윙"
    if c == "hold":
        return "확인 보류"
    return row.get("origin_sector") or "(미분류)"


@st.cache_data(ttl=600)
def load_prices(code: str) -> pd.DataFrame:
    """선택 종목의 일별 시세(prices 테이블)를 읽는다.
    database.py는 수정하지 않고 기존 공개 client()만 사용한다(읽기 전용)."""
    if not code:
        return pd.DataFrame()
    try:
        res = (db.client().table("prices")
               .select("date,close,value")
               .eq("code", code).order("date").execute())
        df = pd.DataFrame(res.data or [])
        if not df.empty and "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame()


# 종목 로고 매핑(심볼→도메인). 나중에 별도 데이터(JSON/CSV)로 쉽게 분리 가능.
# 무료·무키 favicon 서비스(google s2)를 사용하므로 실패해도 fallback 뱃지로 대체된다.
_LOGO_DOMAINS = {
    # ── M7 ──
    "AAPL": "apple.com", "MSFT": "microsoft.com", "NVDA": "nvidia.com",
    "GOOGL": "google.com", "GOOG": "google.com", "AMZN": "amazon.com",
    "META": "meta.com", "TSLA": "tesla.com",

    # ── 글로벌 대형주(공식 도메인 확실한 것만) ──
    "AVGO": "broadcom.com", "ORCL": "oracle.com", "PLTR": "palantir.com",
    "NFLX": "netflix.com", "AMD": "amd.com", "TSM": "tsmc.com",
    "ASML": "asml.com", "ARM": "arm.com", "IONQ": "ionq.com",
    "IREN": "iren.com", "NVO": "novonordisk.com", "LLY": "lilly.com",
    "JPM": "jpmorganchase.com", "V": "visa.com", "MA": "mastercard.com",
    "COIN": "coinbase.com", "MSTR": "microstrategy.com", "CRWD": "crowdstrike.com",
    "SNOW": "snowflake.com", "SHOP": "shopify.com", "UBER": "uber.com",
    "ABNB": "airbnb.com", "DIS": "disney.com", "COST": "costco.com",
    "WMT": "walmart.com",

    # ── 워치리스트 내 기타 해외(확실한 도메인) ──
    "TXN": "ti.com", "QCOM": "qualcomm.com", "MU": "micron.com",
    "MRVL": "marvell.com", "LRCX": "lamresearch.com", "TER": "teradyne.com",
    "DELL": "dell.com", "SMCI": "supermicro.com", "VRT": "vertiv.com",
    "ANET": "arista.com", "NOW": "servicenow.com", "TMUS": "t-mobile.com",
    "NEE": "nexteraenergy.com", "CEG": "constellationenergy.com",
    "LMT": "lockheedmartin.com", "BA": "boeing.com", "NKE": "nike.com",
    "LULU": "lululemon.com", "CROX": "crocs.com", "HOOD": "robinhood.com",
    "UNH": "unitedhealthgroup.com", "MNST": "monsterenergy.com",
    "ETN": "eaton.com", "ALB": "albemarle.com", "OXY": "oxy.com",
    "VLO": "valero.com", "PWR": "quantaservices.com", "DOCN": "digitalocean.com",
    "PLUG": "plugpower.com", "RKLB": "rocketlabusa.com", "JOBY": "jobyaviation.com",
    "NTRA": "natera.com", "TEM": "tempus.com", "CB": "chubb.com",
    "O": "realtyincome.com", "GPN": "globalpayments.com", "FAST": "fastenal.com",
    "ROL": "rollins.com",

    # ── 한국 주요 종목(코드 기준, 공식 도메인 확실한 것만) ──
    "035420": "naver.com",          # NAVER
    "017670": "sktelecom.com",      # SK텔레콤
    "018260": "samsungsds.com",     # 삼성SDS
    "064400": "lgcns.com",          # LG CNS
    "009150": "samsungsem.com",     # 삼성전기
    "373220": "lgensol.com",        # LG에너지솔루션
    "454910": "doosanrobotics.com", # 두산로보틱스
    "034020": "doosanenerbility.com",  # 두산에너빌리티
    "033780": "ktng.com",           # KT&G
    "003490": "koreanair.com",      # 대한항공
    "012330": "mobis.com",          # 현대모비스
    "004170": "shinsegae.com",      # 신세계
    "003230": "samyangfoods.com",   # 삼양식품
    "005490": "posco.com",          # POSCO홀딩스
    "010120": "ls-electric.com",    # LS ELECTRIC
    "042700": "hanmisemiconductor.com",  # 한미반도체
    # 워치리스트엔 아직 없지만 추후 편입 대비(확실한 도메인만)
    "005930": "samsung.com",        # 삼성전자
    "000660": "skhynix.com",        # SK하이닉스
    "005380": "hyundai.com",        # 현대차
    "000270": "kia.com",            # 기아
    "035720": "kakaocorp.com",      # 카카오
    "207940": "samsungbiologics.com",  # 삼성바이오로직스
    "068270": "celltrion.com",      # 셀트리온
    "012450": "hanwhaaerospace.com",   # 한화에어로스페이스
}

_BADGE_PALETTE = ["#4F46E5", "#0EA5E9", "#10B981", "#F59E0B",
                  "#EF4444", "#8B5CF6", "#EC4899", "#14B8A6"]


def get_logo_url(symbol: str, name: str | None = None, market: str | None = None) -> str | None:
    """종목 로고 URL. 매핑된 해외 종목은 favicon URL, 없으면 None(→fallback 뱃지).
    유료/키 필요한 서비스는 쓰지 않는다. 매핑만 늘리면 커버리지가 확장된다."""
    dom = _LOGO_DOMAINS.get(str(symbol or "").upper())
    if dom:
        return f"https://www.google.com/s2/favicons?domain={dom}&sz=64"
    return None


def _badge_color(key: str) -> str:
    s = str(key or "?")
    return _BADGE_PALETTE[sum(ord(c) for c in s) % len(_BADGE_PALETTE)]


def _card_header_html(code: str, name: str, country: str, market: str, sector: str) -> str:
    """카드 상단(로고/뱃지 + 종목명 + 메타 + 섹터 뱃지) HTML. 로고 실패해도 카드 유지."""
    e = html.escape
    url = get_logo_url(code, name, market)
    if url:
        logo = (f"<img src='{e(url)}' alt='' "
                "style='width:34px;height:34px;border-radius:8px;object-fit:contain;"
                "background:#fff;border:1px solid #e5e7eb;flex:none;'>")
    else:
        ch = e((name or code or "?")[:1])
        logo = (f"<div style='width:34px;height:34px;border-radius:8px;background:{_badge_color(code or name)};"
                "color:#fff;display:flex;align-items:center;justify-content:center;"
                "font-weight:600;font-size:15px;flex:none;'>" + ch + "</div>")
    return (
        "<div style='display:flex;align-items:center;gap:10px;'>"
        + logo
        + "<div style='flex:1;min-width:0;'>"
        + f"<div style='font-size:16px;font-weight:600;line-height:1.2;'>{e(name)} "
        + f"<span style='color:#9ca3af;font-weight:400;font-size:13px;'>{e(code)}</span></div>"
        + f"<div style='font-size:12px;color:#6b7280;'>{e(country)} · {e(market)}</div>"
        + "</div>"
        + f"<span style='background:#eef2ff;color:#4338ca;padding:3px 10px;border-radius:12px;"
        + f"font-size:12px;white-space:nowrap;flex:none;'>{e(sector)}</span>"
        + "</div>"
    )


def render_stock_card(row: dict, keyns: str = "map"):
    """종목 1개를 상세 카드로 표시: 기본정보 + 현재가 + 관심가/이격률 + 일봉(지연 로딩).
    관심가는 세션 위젯 상태로만 유지하고 영구 저장하지 않는다(MVP)."""
    code = str(row.get("code", ""))
    name = str(row.get("name", ""))
    country = row.get("country") or "—"
    market = row.get("market") or "—"
    sector = current_sector(row)
    is_kr = country == "KR"
    close = row.get("close")
    has_price = close is not None and not pd.isna(close)

    with st.container(border=True):
        # 헤더: 로고/뱃지 + 종목명 + 국가/시장 + 현재섹터 뱃지
        st.markdown(_card_header_html(code, name, country, market, sector),
                    unsafe_allow_html=True)

        currency = get_currency(row)   # KRW/USD — 환율 변환 없이 현지통화 그대로
        cur_unit = "원" if currency == "KRW" else "$"

        left, right = st.columns([1, 1])
        # 현재가 (통화별 포맷: 78,000원 / $195.74)
        if has_price:
            left.metric("현재가", format_price(close, currency))
        else:
            left.metric("현재가", "—")
            left.caption("💱 해외 현재가 연동 전" if not is_kr else "가격 데이터 없음")

        # 관심가 입력 — 저장값이 있으면 기본값으로 prefill(세션 시드). 종목별 고유 key.
        # DB의 target_price는 통화 무관 numeric 그대로(해석은 country/market 기준).
        tkey = f"{keyns}_t_{code}"
        saved = st.session_state.get("targets", {}).get(code)
        if tkey not in st.session_state:
            st.session_state[tkey] = float(saved) if saved else 0.0
        cur_target = right.number_input(
            f"관심가 입력({cur_unit})", min_value=0.0,
            step=100.0 if currency == "KRW" else 0.5, key=tkey)

        # 이격률 (현재 입력값 기준). 색상: |이격률|≤5 빨강(근접), >5 초록.
        if has_price and cur_target > 0:
            gap = (float(close) - float(cur_target)) / float(cur_target) * 100.0
            near = abs(gap) <= 5
            color = "#DC2626" if near else "#16A34A"
            meaning = "관심가 근접" if near else "거리 있음"
            right.markdown(
                f"<div style='font-size:12px;color:#6b7280;margin-bottom:-6px;'>이격률 · {meaning}</div>"
                f"<div style='font-size:22px;font-weight:600;color:{color};'>{gap:+.2f}%</div>",
                unsafe_allow_html=True,
            )
        elif not has_price:
            right.caption("현재가 연동 후 이격률 계산")
        else:
            right.caption("관심가 입력 시 이격률 표시")

        # 저장 / 해제 (A안: 버튼 클릭 시에만 DB 반영) + 저장 상태 표시
        b1, b2, b3 = st.columns([1, 1, 2])
        if b1.button("💾 저장", key=f"{keyns}_save_{code}", use_container_width=True):
            try:
                if cur_target and cur_target > 0:
                    db.set_target(code, float(cur_target))
                    st.session_state.setdefault("targets", {})[code] = float(cur_target)
                    st.toast(f"{name} 관심가 저장 · {format_price(cur_target, currency)}")
                else:
                    db.delete_target(code)
                    st.session_state.setdefault("targets", {}).pop(code, None)
                    st.toast("관심가가 0이라 해제 처리했어요. 값을 입력 후 저장하세요.")
            except Exception as e:
                st.error(f"저장 실패: {e}")
        if b2.button("✖ 해제", key=f"{keyns}_clear_{code}", use_container_width=True):
            try:
                db.delete_target(code)
                st.session_state.setdefault("targets", {}).pop(code, None)
                st.session_state[tkey] = 0.0
                st.toast(f"{name} 관심가 해제됨")
                st.rerun()
            except Exception as e:
                st.error(f"해제 실패: {e}")
        saved_after = st.session_state.get("targets", {}).get(code)
        b3.caption(f"💾 DB 저장값 {format_price(saved_after, currency)}" if saved_after else "미저장")

        # 일봉 차트 (펼친 뒤 체크 시에만 조회 → 화면 가벼움)
        with st.expander("📈 최근 6개월 일봉 차트"):
            if not is_kr and not has_price:
                st.caption("해외 종목 일봉은 2차 단계에서 연동 예정입니다.")
            elif st.checkbox("차트 표시", key=f"{keyns}_c_{code}"):
                pr = load_prices(code)
                if pr.empty or "close" not in pr.columns:
                    st.caption("가격 데이터 없음")
                else:
                    st.line_chart(
                        pr.set_index("date")[["close"]].rename(columns={"close": "종가"}),
                        height=220,
                    )
                    st.caption(f"최근 {len(pr)}거래일 종가 · DB prices 기준")


def main():
    if not gate():
        return

    stocks, history, last_update, last_date = load_data()

    # 관심가(stock_targets)를 세션에 1회 시드 — 이후 저장/해제로 in-place 갱신.
    # 조회 실패해도 get_targets()가 {} 반환하므로 화면은 유지된다.
    if "targets" not in st.session_state:
        st.session_state["targets"] = db.get_targets()

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
        return d.apply(current_sector, axis=1)

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

    # 3) 섹터 구성 — 메뉴형 섹터맵: 메뉴(전체/단기스윙/M7/섹터) 선택 → 종목을 상세 카드로
    with tabs[2]:
        base = apply_filters(stocks).copy()
        base["__cat"] = cur_cat_series(base)
        order_key = lambda c: (c != "단기스윙", c == "확인 보류", str(c))
        cats_all = sorted(base["__cat"].dropna().unique(), key=order_key)
        menu = ["전체"] + cats_all
        default_idx = menu.index("단기스윙") if "단기스윙" in menu else 0
        choice = st.radio("섹터 메뉴", menu, horizontal=True,
                          index=default_idx, key="sector_menu")

        if choice == "전체":
            sub = base
            title = f"📂 전체 — {len(sub)}종목"
        else:
            sub = base[base["__cat"] == choice]
            label = "🔹 단기스윙 (1,000억 이하 · 섹터 통합)" if choice == "단기스윙" else f"🗂 {choice}"
            title = f"{label} — {len(sub)}종목"
        st.subheader(title)
        st.divider()

        if sub.empty:
            st.info("해당 메뉴에 표시할 종목이 없습니다. (사이드바 필터를 확인하세요)")
        else:
            if len(sub) > 60:
                st.caption(f"종목이 많아({len(sub)}개) 로딩이 다소 걸릴 수 있어요. 메뉴로 좁혀 보세요.")
            for rec in sub.to_dict("records"):
                render_stock_card(rec, keyns="map")

        csv_download(base.drop(columns="__cat").assign(현재섹터=cur_cat_series(base)),
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
