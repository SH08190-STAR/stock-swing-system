"""
app.py — Z PICK 한국주식 워치리스트 대시보드 (Streamlit)

내비게이션(모바일 중심 — UI 1단계 재편): 최상위 4탭
 홈(요약) / 섹터(섹터 구성·종목 카드) / 매매(매매 기록) / 더보기(저빈도 조회)

기존 요구 9종 기능은 삭제 없이 재배치:
 전체·단기스윙·거래대금 순위·신규 편입·분류 이탈·변경 이력·확인 보류 → 더보기,
 기존 섹터별 → 섹터 탭, 마지막 최신화 시각 → 상단 고정 캡션.
검색은 화면당 최대 2개: 상단 통합 검색 + 현재 화면 내부 검색(섹터/매매).

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

# ── 전역 스타일 (폴리시 단계 — 표시만 담당, 기능은 CSS 미적용 시에도 동일 동작) ──
# 원칙: 배경 연회색/카드 흰색, radius 16~20px, 약한 그림자, 주색 1개(#3182f6),
#       숫자·상태 강조, 보조 정보는 작은 회색, 좌우 여백 14~16px.
_GLOBAL_CSS = """
/* 레이아웃: 배경·여백·상단 축소 */
.stApp { background:#f2f4f6; color:#191f28; }
[data-testid="stHeader"] { background:transparent; }
.block-container { padding-top:1.1rem; padding-bottom:3rem;
  padding-left:16px; padding-right:16px; max-width:820px; }
.stApp, .block-container { overflow-x:hidden; }
@media (max-width:480px){
  .block-container { padding-left:14px; padding-right:14px; } }
hr { margin:.7rem 0; border-color:#e5e8eb; }
[data-testid="stVerticalBlock"] { gap:.65rem; }

/* 텍스트 계층: 보조 정보는 작은 회색(최소 13px) */
[data-testid="stCaptionContainer"] { color:#8b95a1 !important;
  font-size:13px !important; }
[data-testid="stCaptionContainer"] p { margin-bottom:0; line-height:1.35; }

/* 최상위 4탭 → 둥근 세그먼트형 (선택만 흰색 강조, 가로 균등 분할) */
.stTabs [data-baseweb="tab-list"] { background:#e8eaed; border-radius:14px;
  padding:4px; gap:4px; display:flex; width:100%; }
.stTabs [data-baseweb="tab"] { flex:1 1 0; justify-content:center;
  height:38px; border-radius:11px; font-size:14px; font-weight:600;
  color:#6b7684; background:transparent; padding:0 4px; }
.stTabs [aria-selected="true"] { background:#fff; color:#191f28;
  box-shadow:0 1px 3px rgba(0,0,0,.06); }
.stTabs [data-baseweb="tab-highlight"],
.stTabs [data-baseweb="tab-border"] { display:none; }

/* 카드: st.container(border=True) → 흰색 라운드 카드 + 약한 그림자.
   Streamlit 버전별 DOM 차이에 안전하도록 카드 첫 markdown의 .zp-card 마커로 식별,
   구버전 wrapper 선택자도 병행. 미적용 시 기본 테두리 카드로 동작(기능 무영향). */
[data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .zp-card) {
  background:#fff !important; border:1px solid #eceef1 !important;
  border-radius:18px !important; box-shadow:0 1px 3px rgba(25,31,40,.04); }
div[data-testid="stVerticalBlockBorderWrapper"] { background:#fff;
  border-radius:18px; border:1px solid #eceef1;
  box-shadow:0 1px 3px rgba(25,31,40,.04); }
div[data-testid="stVerticalBlockBorderWrapper"] > div {
  border:none !important; border-radius:18px; }

/* expander: 카드 안 보조 요소로 (시각적 중심 금지) */
[data-testid="stExpander"] details { border:1px solid #eef0f3;
  border-radius:12px; background:#fafbfc; }
[data-testid="stExpander"] summary { font-size:13px; color:#6b7684; }

/* metric: 숫자 크고 진하게, 라벨은 보조 계층 */
[data-testid="stMetricLabel"] { font-size:13px; color:#8b95a1; }
[data-testid="stMetricValue"] { font-size:1.5rem; font-weight:700;
  letter-spacing:-.3px; color:#191f28; line-height:1.15; }
[data-testid="stMetric"] { gap:2px; }

/* 보조 텍스트 정렬: metric 바로 다음 caption(환산가·52주 고점 등)을
   큰 숫자에 붙여 표시 — 블록 gap(.65rem)만 상쇄, 다른 caption엔 영향 없음 */
[data-testid="stElementContainer"]:has(> [data-testid="stMetric"])
  + [data-testid="stElementContainer"]:has([data-testid="stCaptionContainer"]) {
  margin-top:-9px; }

/* 검색·입력: 둥근 모서리 + 연한 테두리로 통일 */
.stTextInput [data-baseweb="input"], .stNumberInput [data-baseweb="input"],
.stDateInput [data-baseweb="input"],
.stSelectbox [data-baseweb="select"] > div { border-radius:12px;
  background:#fff; border-color:#e5e8eb; }
.stTextInput input::placeholder { color:#b0b8c1; }

/* 버튼: 높이·radius·글자 크기 통일, primary는 주색 1개 */
.stButton button, .stDownloadButton button, .stFormSubmitButton button {
  border-radius:12px; min-height:40px; font-size:14px;
  border:1px solid #e5e8eb; }
.stButton button[kind="primary"],
.stFormSubmitButton button[kind="primary"] { background:#3182f6;
  border-color:#3182f6; }

/* pills 칩: 선택만 진한 배경, 높이·간격 고정 */
button[data-testid="stBaseButton-pills"],
button[data-testid="stBaseButton-pillsActive"] { border-radius:999px;
  min-height:34px; padding:2px 14px; font-size:13px; white-space:nowrap; }
button[data-testid="stBaseButton-pills"] { background:#fff; color:#4e5968;
  border:1px solid #e5e8eb; }
button[data-testid="stBaseButton-pillsActive"] { background:#191f28;
  color:#fff; border:1px solid #191f28; }

/* radio(시장/상태 등) → 칩 모양 (미적용 브라우저에서도 기능 동일) */
.stRadio [role="radiogroup"] { gap:8px; flex-wrap:wrap; }
.stRadio [role="radiogroup"] label { background:#fff;
  border:1px solid #e5e8eb; border-radius:999px; padding:5px 14px;
  margin:0; min-height:34px; align-items:center; }
.stRadio [role="radiogroup"] label:has(input:checked) { background:#191f28;
  border-color:#191f28; }
.stRadio [role="radiogroup"] label:has(input:checked) p { color:#fff; }
.stRadio [role="radiogroup"] label > div:first-child { display:none; }
"""
st.markdown(f"<style>{_GLOBAL_CSS}</style>", unsafe_allow_html=True)


def pnl_color(v) -> str | None:
    """완료 손익 표시색: 수익 빨강 / 손실 파랑 (국내 증권 규칙) / 0·숫자 아님 중립.
    숫자로 못 읽으면 None(색 미적용)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if pd.isna(f):
        return None
    if f > 0:
        return "#f04452"
    if f < 0:
        return "#3182f6"
    return "#333d4b"


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
                "close", "change_pct", "used_days", "estimated", "data_date", "reason",
                "high_52w"]
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


def select_pills(label: str, options, default_idx: int = 0, key=None):
    """모바일 가로 선택 메뉴: st.pills(Streamlit 1.40+) 사용,
    미지원 버전은 기존 radio(horizontal)로 안전 폴백.
    pills는 선택 해제(None)가 가능하므로 None이면 기본값으로 되돌린다."""
    options = list(options)
    if not options:
        return None
    if default_idx < 0 or default_idx >= len(options):
        default_idx = 0
    if hasattr(st, "pills"):
        sel = st.pills(label, options, selection_mode="single",
                       default=options[default_idx], key=key)
        return sel if sel is not None else options[default_idx]
    return st.radio(label, options, horizontal=True, index=default_idx, key=key)


def render_filters(stocks: pd.DataFrame, key_prefix: str, with_search: bool = False):
    """구(舊) 사이드바 필터 → 메인 화면 expander로 이동 (필터 로직 동일, 기능 삭제 없음).
    반환: DataFrame 필터 함수. 검색 필드는 자체 검색이 없는 화면(더보기)에서만 노출해
    화면당 검색창을 최대 2개(통합 + 현재 화면)로 유지한다."""
    with st.expander("⚙️ 필터 — 국가·시장·섹터·정렬"):
        q = st.text_input("종목명·코드 검색", key=f"{key_prefix}_fq") if with_search else ""
        country_opts = sorted([c for c in stocks.get("country", pd.Series(dtype=str)).dropna().unique() if c])
        country_sel = st.multiselect("국가", country_opts, default=country_opts,
                                     key=f"{key_prefix}_fcountry")
        market_opts = sorted([m for m in stocks["market"].dropna().unique() if m])
        markets = st.multiselect("시장", market_opts, default=market_opts,
                                 key=f"{key_prefix}_fmarket")
        sectors = sorted([s for s in stocks["origin_sector"].dropna().unique() if s])
        sec_sel = st.multiselect("기존 섹터", sectors, default=sectors,
                                 key=f"{key_prefix}_fsector")
        sort_by_value = st.checkbox("거래대금순 정렬", value=True, key=f"{key_prefix}_fsort")

    def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
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
    return apply_filters


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


def calc_gap_from_high(current_price, high_52w):
    """고점 대비 이격률 = (현재가 − 52주 고점) / 고점 × 100 (보통 음수).
    현재가/고점이 없거나 0 이하이면 None."""
    try:
        for v in (current_price, high_52w):
            if v is None or pd.isna(v) or float(v) <= 0:
                return None
        return (float(current_price) - float(high_52w)) / float(high_52w) * 100.0
    except (TypeError, ValueError):
        return None


def format_52w_high_line(row) -> str:
    """카드용 한 줄: '52주 고점 91,000원 · 고점 대비 -12.5%'.
    고점 없으면 '52주 고점 —', 이격률 계산 불가면 가격만 표시(예외 없음)."""
    currency = get_currency(row)
    h = row.get("high_52w")
    try:
        has_high = h is not None and not pd.isna(h) and float(h) > 0
    except (TypeError, ValueError):
        has_high = False
    if not has_high:
        return "52주 고점 —"
    line = f"52주 고점 {format_price(h, currency)}"
    gap = calc_gap_from_high(row.get("close"), h)
    if gap is not None:
        line += f" · 고점 대비 {gap:+.1f}%"
    return line


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
        "<div class='zp-card' style='display:flex;align-items:center;gap:10px;'>"
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
        # 52주 고점 + 고점 대비 이격률 (중립 회색 캡션 — 관심가 색상과 분리)
        left.caption(format_52w_high_line(row))

        # 매매 기록 연동 (관심가 UI 대체 — stock_targets 데이터/함수는 보존, UI만 숨김)
        # waiting/entered/tp_in 기록을 최대 3줄 표시. completed 제외.
        link_lines = trade_link_lines(row, currency)
        if link_lines:
            right.markdown("<div style='font-size:12px;color:#6b7280;'>📌 매매 기록</div>",
                           unsafe_allow_html=True)
            for ln in link_lines:
                right.caption(ln)
        else:
            right.caption("연동된 매매 기록 없음")

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


# ── 통합/로컬 검색 헬퍼 (read-only 로컬 필터링 — DB 반복 호출 없음) ──
def normalize_search_query(query) -> str:
    return str(query or "").strip().lower()


def stock_match_rank(row, query):
    """종목 매칭 순위: 0=코드 완전일치(zfill 대응) 1=이름 완전일치 2=앞부분 3=포함. 불일치 None."""
    q = normalize_search_query(query).replace(" ", "")
    if not q:
        return None
    code = str(row.get("code") or "").strip().lower()
    name = str(row.get("name") or "").replace(" ", "").lower()
    if not code and not name:
        return None
    qz = q.zfill(6) if q.isdigit() and len(q) < 6 else q   # 5930 → 005930
    if q == code or qz == code:
        return 0
    if q == name:
        return 1
    if (qz and code.startswith(qz)) or (name and name.startswith(q)):
        return 2
    if (qz and qz in code) or (q and q in name):
        return 3
    return None


def filter_stocks_by_query(df, query):
    """DataFrame 로컬 필터. 빈 검색어면 원본 그대로."""
    q = normalize_search_query(query)
    if not q or df is None or len(df) == 0:
        return df
    mask = df.apply(lambda r: stock_match_rank(r, q) is not None, axis=1)
    return df[mask]


def trade_matches_query(r: dict, query, name_map: dict | None = None) -> bool:
    """매매기록 매칭: symbol/종목명/leverage_symbol/memo/status/record_date. 빈 검색어=True."""
    q = normalize_search_query(query)
    if not q:
        return True
    qz = q.zfill(6) if q.isdigit() and len(q) < 6 else None
    fields = [r.get("symbol"), r.get("leverage_symbol"), r.get("memo"),
              r.get("status"), _ST_LABEL.get(r.get("status"), ""),
              str(r.get("record_date") or "")]
    if name_map:
        sym = normalize_symbol(r.get("symbol"), r.get("market_group"))
        fields.append(name_map.get(str(sym)))
    for f in fields:
        s = str(f or "").strip().lower()
        if not s:
            continue
        if q in s or (qz and qz in s):
            return True
    return False


@st.cache_data(ttl=600)
def load_all_trades() -> list:
    """전 상태(완료 포함) 매매기록 1회 로드(통합 검색용, 캐시)."""
    try:
        return db.list_trade_records() or []
    except Exception:
        return []


@st.cache_data(ttl=600)
def stock_name_map() -> dict:
    """symbol→종목명 매핑(워치리스트 기반, 매매기록 종목명 검색용)."""
    try:
        return {str(r["symbol"]): str(r.get("name") or "") for r in wl.load_all()}
    except Exception:
        return {}


# ── 매매 기록 (trade_records) ────────────────────────────────
TRADE_SQL = """create table if not exists trade_records (
    id             uuid primary key default gen_random_uuid(),
    market_group   text not null,
    status         text not null,
    record_date    date not null,
    symbol         text not null,
    leverage_symbol text,
    entry1 numeric, entry2 numeric, entry3 numeric, entry4 numeric,
    tp1 numeric, tp2 numeric,
    stop numeric,
    risk1 numeric, risk2 numeric, risk3 numeric, risk4 numeric,
    realized_tp1_profit numeric,
    realized_tp2_profit numeric,
    realized_stop_loss  numeric,
    realized_total_pnl  numeric,
    memo text,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);
create index if not exists idx_trade_records_group_status
    on trade_records(market_group, status);"""

_ST_LABEL = {"waiting": "대기중", "entered": "진입", "tp_in": "TP IN", "completed": "완료"}
_ST_CODE = {v: k for k, v in _ST_LABEL.items()}


def lev_convert(etf_now, base_now, target):
    """레버리지 ETF 환산가(2배 고정): etf_now × (1 + (target-base_now)/base_now × 2).
    가격이 없거나(None/NaN) 0·음수면 계산하지 않고 None."""
    try:
        for v in (etf_now, base_now, target):
            if v is None or pd.isna(v):
                return None
        etf_now, base_now, target = float(etf_now), float(base_now), float(target)
        if etf_now <= 0 or base_now <= 0 or target <= 0:
            return None
        return etf_now * (1 + (target - base_now) / base_now * 2)
    except (TypeError, ValueError):
        return None


def kst_now_str() -> str:
    """한국시간 기준시각 문자열: 'YYYY-MM-DD HH:mm KST'."""
    kst = dt.timezone(dt.timedelta(hours=9))
    return dt.datetime.now(kst).strftime("%Y-%m-%d %H:%M KST")


def calc_position_qty(entry_lev_price, stop_lev_price, risk_amount):
    """계획 수량 = 진입 리스크 ÷ 주당 리스크(진입 환산가 − 손절 환산가).
    일반 반올림(4.49→4, 4.50→5 — 파이썬 round는 은행가 방식이라 floor(x+0.5) 사용).
    값 누락/주당 리스크 0 이하/리스크 0 이하면 None. 표시 전용(주문 기능 아님)."""
    import math
    try:
        for v in (entry_lev_price, stop_lev_price, risk_amount):
            if v is None or pd.isna(v):
                return None
        per_share = float(entry_lev_price) - float(stop_lev_price)
        if per_share <= 0 or float(risk_amount) <= 0:
            return None
        return int(math.floor(float(risk_amount) / per_share + 0.5))
    except (TypeError, ValueError):
        return None


@st.cache_data(ttl=600)
def latest_price(symbol: str):
    """본주/ETF 최신가: stocks→prices(DB) 우선, 없으면 FDR 1회 조회(캐시 10분)."""
    if not symbol:
        return None
    p = db.get_latest_price(symbol)
    if p:
        return p
    try:  # DB에 없는 레버리지 ETF 등 — FDR fallback (실패해도 화면 유지)
        import FinanceDataReader as fdr
        import datetime as _dt
        end = _dt.date.today()
        df = fdr.DataReader(symbol, (end - _dt.timedelta(days=14)).isoformat(), end.isoformat())
        if df is not None and len(df) and "Close" in df.columns:
            v = float(df["Close"].dropna().iloc[-1])
            return v if v > 0 else None
    except Exception:
        pass
    return None


def normalize_symbol(symbol, market_group: str | None = None) -> str:
    """조회/저장용 심볼 정규화. 기존 DB 데이터는 건드리지 않고 입력·조회 시점에만 적용.
    - 숫자만이면 한국 코드로 보고 zfill(6): '5930' → '005930'
    - KR의 비숫자(한글 종목명 등)는 그대로(이름 보조조회용)
    - 그 외(미국 티커)는 대문자"""
    s = str(symbol or "").strip()
    if not s:
        return s
    if s.isdigit():
        return s.zfill(6)
    if market_group == "KR":
        return s
    return s.upper()


@st.cache_data(ttl=600)
def kr_code_by_name(name: str):
    """한국 종목명 정확일치 → 코드 (stocks 테이블, 유일 일치일 때만). 읽기 전용."""
    try:
        res = db.client().table("stocks").select("code").eq("name", str(name).strip()).execute()
        if res.data and len(res.data) == 1:
            return res.data[0]["code"]
    except Exception:
        pass
    return None


def trade_price(symbol, market_group: str | None = None):
    """매매 기록용 가격 조회: 정규화 → latest_price(stocks→prices→FDR).
    KR에서 이름으로 입력된 경우 정확일치 이름→코드 보조조회."""
    s = normalize_symbol(symbol, market_group)
    if not s:
        return None
    p = latest_price(s)
    if p is None and market_group == "KR" and not s.isdigit():
        code = kr_code_by_name(s)
        if code:
            p = latest_price(str(code))
    return p


def _fmtp(v, currency):
    return format_price(v, currency) if v is not None else "—"


def calc_total_pnl(tp1, tp2, tp3, stop_loss):
    """완료 총 손익 = 1차+2차+3차 익절 금액 − abs(손절액).
    None/NaN은 0으로. 손절액은 음수로 입력돼도 abs 처리(이중 음수 방지)."""
    def n(v):
        try:
            if v is None or pd.isna(v):
                return 0.0
            return float(v)
        except (TypeError, ValueError):
            return 0.0
    return n(tp1) + n(tp2) + n(tp3) - abs(n(stop_loss))


def trade_display_price(r: dict):
    """섹터 카드 연동용 (라벨, 표시가격). 표시가격 없으면 (라벨, None) 또는 (None, None).
    waiting/entered: entry1→2→3→4 첫 값. tp_in: 미실현 tp1→tp2→stop 순."""
    def first_entry():
        for i in (1, 2, 3, 4):
            v = r.get(f"entry{i}")
            if v:
                return float(v)
        return None
    status = r.get("status")
    if status == "waiting":
        return ("대기중", first_entry())
    if status == "entered":
        return ("진입", first_entry())
    if status == "tp_in":
        if not r.get("realized_tp1_profit") and r.get("tp1"):
            return ("TP IN 다음 목표", float(r["tp1"]))
        if not r.get("realized_tp2_profit") and r.get("tp2"):
            return ("TP IN 다음 목표", float(r["tp2"]))
        if r.get("stop"):
            return ("TP IN 손절가", float(r["stop"]))
        return ("TP IN", None)
    return (None, None)


def gap_vs_current(target, current):
    """(표시가격 − 현재가) / 현재가 × 100. 값 없거나 0 이하이면 None."""
    try:
        for v in (target, current):
            if v is None or pd.isna(v) or float(v) <= 0:
                return None
        return (float(target) - float(current)) / float(current) * 100.0
    except (TypeError, ValueError):
        return None


_TRADE_PRI = {"entered": 0, "tp_in": 1, "waiting": 2}


@st.cache_data(ttl=600)
def load_active_trades() -> dict:
    """진행중(waiting/entered/tp_in) 매매 기록을 1회 로드해 정규화 심볼→기록목록 매핑.
    섹터 카드 연동용(캐시 — N+1 쿼리 방지). 정렬: entered→tp_in→waiting, 상태 내 최신순."""
    try:
        recs = db.list_trade_records() or []
    except Exception:
        recs = []
    out: dict[str, list] = {}
    for r in recs:
        if r.get("status") not in ("waiting", "entered", "tp_in"):
            continue
        sym = normalize_symbol(r.get("symbol"), r.get("market_group"))
        if r.get("market_group") == "KR" and sym and not sym.isdigit():
            code = kr_code_by_name(sym)      # 종목명 입력 기록 → 코드 매칭(정확일치)
            if code:
                sym = str(code)
        if sym:
            out.setdefault(sym, []).append(r)
    for lst in out.values():
        lst.sort(key=lambda r: str(r.get("record_date") or ""), reverse=True)
        lst.sort(key=lambda r: _TRADE_PRI.get(r.get("status"), 9))
    return out


def format_trade_line(r: dict, currency: str, current_price=None):
    """매매기록 1건 → 카드 연동 한 줄. 종목코드는 카드 헤더에 있으므로 반복하지 않는다.
    예) 진입 7/6 · 12,300원 · 현재가 대비 +4.0%
        대기중 7/21 · 진입 예정 10,500원 · 현재가 대비 -11.2%
        TP IN 7/9 · 다음 목표 15,000원 · 현재가 대비 +8.5%
    가격이 없으면 '진입가 —'/'진입 예정 —'/'목표가 —' — symbol을 가격 대신 쓰지 않는다."""
    label, price = trade_display_price(r)
    if label is None:
        return None
    try:
        d = dt.date.fromisoformat(str(r.get("record_date")))
        dstr = f"{d.month}/{d.day}"
    except (ValueError, TypeError):
        dstr = ""                     # 날짜 이상해도 앱은 유지(날짜만 생략)
    if label == "진입":
        prefix, ptxt = "진입", (format_price(price, currency) if price else "진입가 —")
    elif label == "대기중":
        prefix, ptxt = "대기중", (f"진입 예정 {format_price(price, currency)}" if price else "진입 예정 —")
    elif label == "TP IN 다음 목표":
        prefix, ptxt = "TP IN", f"다음 목표 {format_price(price, currency)}"
    elif label == "TP IN 손절가":
        prefix, ptxt = "TP IN", f"손절가 {format_price(price, currency)}"
    elif label == "TP IN":
        prefix, ptxt = "TP IN", "목표가 —"
    else:
        return None
    parts = [f"{prefix} {dstr}".strip(), ptxt]
    gap = gap_vs_current(price, current_price)
    if gap is not None:
        parts.append(f"현재가 대비 {gap:+.1f}%")
    return " · ".join(parts)


def trade_link_lines(row, currency: str, max_lines: int = 3) -> list[str]:
    """섹터 카드용 매매기록 연동 줄(최대 3줄 + '외 N건')."""
    recs = load_active_trades().get(str(row.get("code") or ""), [])
    lines = []
    for r in recs[:max_lines]:
        line = format_trade_line(r, currency, row.get("close"))
        if line:
            lines.append(line)
    if len(recs) > max_lines:
        lines.append(f"외 {len(recs) - max_lines}건")
    return lines


def _plain_target(t):
    """본주 단독 모드의 '환산가' = 본주 목표가 그대로(유효값만)."""
    try:
        if t is None or pd.isna(t) or float(t) <= 0:
            return None
        return float(t)
    except (TypeError, ValueError):
        return None


def _trade_calc(r: dict):
    """기록 1건의 파생값 계산: 현재가·환산가·주당리스크·수량. 표시 전용.
    레버리지 ETF가 있으면 2배 환산, 없으면 본주 가격 그대로(본주 단독 매매)."""
    mg = r.get("market_group")
    base_now = trade_price(r.get("symbol"), mg)
    lev_sym = str(r.get("leverage_symbol") or "").strip()
    if lev_sym:
        etf_now = trade_price(lev_sym, mg)
        conv = lambda t: lev_convert(etf_now, base_now, t)
        trade_now = etf_now
    else:
        etf_now = None
        conv = _plain_target          # 본주 단독: 환산가 = 본주 목표가
        trade_now = base_now
    stop_lev = conv(r.get("stop"))
    out = {"base_now": base_now, "etf_now": etf_now, "stop_lev": stop_lev,
           "conv": conv, "trade_now": trade_now, "is_lev": bool(lev_sym)}
    for i in (1, 2, 3, 4):
        e_lev = conv(r.get(f"entry{i}"))
        out[f"e{i}_lev"] = e_lev
        out[f"qty{i}"] = calc_position_qty(e_lev, stop_lev, r.get(f"risk{i}"))
    risks = [r.get(f"risk{i}") for i in (1, 2, 3, 4)]
    out["total_risk"] = sum(float(x) for x in risks if x) or None
    return out


_BADGE_STYLES = {
    "waiting": ("#E5E7EB", "#374151"), "entered": ("#DBEAFE", "#1D4ED8"),
    "tp_in": ("#FEF3C7", "#92400E"), "completed": ("#DCFCE7", "#166534"),
}


def _badge(text, bg, fg):
    return (f"<span style='background:{bg};color:{fg};padding:2px 10px;border-radius:12px;"
            f"font-size:12px;margin-right:6px;white-space:nowrap;'>{html.escape(str(text))}</span>")


def _render_trade_card(r: dict, currency: str):
    """기록 1건을 카드형으로: 배지(상태/시장/본주·레버리지) + 핵심 수치 + 상세 expander.
    모바일 가로 스크롤 최소화 목적(표 대신 카드)."""
    c = _trade_calc(r)
    status = r.get("status")
    bg, fg = _BADGE_STYLES.get(status, ("#E5E7EB", "#374151"))
    lev_sym = str(r.get("leverage_symbol") or "").strip()
    badges = (
        _badge(_ST_LABEL.get(status, status), bg, fg)
        + _badge("국장" if r.get("market_group") == "KR" else "미장", "#F1F5F9", "#475569")
        + (_badge(f"2× {lev_sym}", "#F5F3FF", "#6D28D9") if lev_sym
           else _badge("본주", "#F1F5F9", "#475569"))
    )
    with st.container(border=True):
        st.markdown(
            f"<div class='zp-card' style='display:flex;align-items:center;gap:8px;flex-wrap:wrap;'>"
            f"<span style='font-size:17px;font-weight:600;'>{html.escape(str(r.get('symbol') or ''))}</span>"
            f"<span style='color:#9ca3af;font-size:12px;'>{html.escape(str(r.get('record_date') or ''))}</span>"
            f"<span>{badges}</span></div>",
            unsafe_allow_html=True)
        m1, m2, m3 = st.columns(3)
        m1.metric("본주 현재가", _fmtp(c["base_now"], currency))
        m2.metric("거래 현재가" + (" · ETF" if c["is_lev"] else " · 본주"),
                  _fmtp(c["trade_now"], currency))
        m3.metric("1차 진입", _fmtp(r.get("entry1"), currency))
        n1, n2, n3 = st.columns(3)
        n1.metric("1차 수량", c["qty1"] if c["qty1"] is not None else "—")
        n2.metric("손절", _fmtp(r.get("stop"), currency))
        n2.caption(f"환산 {_fmtp(c['stop_lev'], currency)}")
        if status == "completed":
            pnl = r.get("realized_total_pnl")
            color = pnl_color(pnl)
            if pnl is None or color is None:
                n3.metric("총 손익", "—")
            else:
                # 수익 빨강/손실 파랑만 절제해 표시 (metric은 색 지정 불가 → 동급 마크업)
                n3.markdown(
                    "<div style='font-size:13px;color:#8b95a1;'>총 손익</div>"
                    f"<div style='font-size:1.5rem;font-weight:700;color:{color};"
                    f"letter-spacing:-.3px;'>{float(pnl):+,.0f}</div>",
                    unsafe_allow_html=True)
        else:
            n3.metric("총 계획 리스크", c["total_risk"] if c["total_risk"] else "—")
        if c["trade_now"] is None:
            st.caption("💡 거래 가격 미조회 — 티커 확인(한국은 6자리 코드 권장) 또는 가격 새로고침을 눌러보세요.")
        if r.get("memo"):
            st.caption(f"📝 {r['memo']}")
        _render_trade_detail(r, currency)


def _render_trade_detail(r: dict, currency: str):
    """기록 1건 상세 expander: 기본정보 / 진입계획(수량) / 익절·손절 / 완료손익."""
    c = _trade_calc(r)
    with st.expander("📋 상세 보기 — 1~4차 계획 · 익절/손절" +
                     (" · 완료 손익" if r.get("status") == "completed" else "")):
        # 1. 기본 정보
        b1, b2, b3, b4 = st.columns(4)
        b1.metric("본주 현재가", _fmtp(c["base_now"], currency))
        b2.metric("거래 현재가" + (" · ETF" if c["is_lev"] else " · 본주"),
                  _fmtp(c["trade_now"], currency))
        b3.metric("시장", "국장" if r.get("market_group") == "KR" else "미장")
        b4.metric("상태", _ST_LABEL.get(r.get("status"), "—"))

        # 2. 진입 계획 (환산가·주당 리스크·수량) — 본주 단독이면 환산가=본주가
        plan = []
        for i in (1, 2, 3, 4):
            e, e_lev, risk, qty = r.get(f"entry{i}"), c[f"e{i}_lev"], r.get(f"risk{i}"), c[f"qty{i}"]
            if e is None and risk is None:
                continue
            per = (e_lev - c["stop_lev"]) if (e_lev is not None and c["stop_lev"] is not None) else None
            plan.append({
                "구분": f"{i}차", "본주 진입가": _fmtp(e, currency),
                "환산가": _fmtp(e_lev, currency),
                "손절 환산가": _fmtp(c["stop_lev"], currency),
                "주당 리스크": _fmtp(per, currency) if per is not None else "—",
                "입력 리스크": risk if risk is not None else "—",
                "계산 수량": qty if qty is not None else "—",
            })
        if plan:
            st.markdown("**진입 계획**")
            st.dataframe(pd.DataFrame(plan), use_container_width=True, hide_index=True)

        # 3. 익절/손절 (환산가 포함)
        st.markdown("**익절 / 손절**")
        t1, t2, t3 = st.columns(3)
        t1.metric("1차 익절", _fmtp(r.get("tp1"), currency))
        t1.caption(f"환산 {_fmtp(c['conv'](r.get('tp1')), currency)}")
        t2.metric("2차 익절", _fmtp(r.get("tp2"), currency))
        t2.caption(f"환산 {_fmtp(c['conv'](r.get('tp2')), currency)}")
        t3.metric("손절", _fmtp(r.get("stop"), currency))
        t3.caption(f"환산 {_fmtp(c['stop_lev'], currency)}")

        # 4. 완료 손익 (완료 상태만 — 총 손익은 저장 시 자동 계산값)
        if r.get("status") == "completed":
            st.markdown("**완료 손익**")
            p1, p2, p3, p4, p5 = st.columns(5)
            p1.metric("1차 익절 금액", r.get("realized_tp1_profit") if r.get("realized_tp1_profit") is not None else "—")
            p2.metric("2차 익절 금액", r.get("realized_tp2_profit") if r.get("realized_tp2_profit") is not None else "—")
            p3.metric("3차 익절 금액", r.get("realized_tp3_profit") if r.get("realized_tp3_profit") is not None else "—")
            p4.metric("손절액", r.get("realized_stop_loss") if r.get("realized_stop_loss") is not None else "—")
            p5.metric("총 손익", r.get("realized_total_pnl") if r.get("realized_total_pnl") is not None else "—")


def render_trade_tab():
    # 가격 기준시각 + 새로고침 (latest_price 캐시만 표적 초기화 — 다른 탭 캐시 무영향)
    if "price_asof" not in st.session_state:
        st.session_state["price_asof"] = kst_now_str()
    h1, h2 = st.columns([2.2, 1])
    h1.markdown(f"**가격 기준:** {st.session_state['price_asof']}")
    if h2.button("🔄 가격 새로고침", key="tr_price_refresh", use_container_width=True):
        latest_price.clear()                       # 화면 계산용 가격 캐시 초기화
        st.session_state["price_asof"] = kst_now_str()
        st.toast("가격 기준을 새로고침했습니다 — 환산가/수량을 다시 계산합니다")
        st.rerun()
    st.caption("본주 현재가는 Supabase DB 최신값(매 거래일 자동 갱신) 기준, 레버리지 ETF는 DB 또는 FDR 조회 기준입니다. "
               "새로고침 버튼은 화면 계산용 가격 캐시를 초기화해 환산가/수량을 다시 계산하며, "
               "DB 전체 가격을 새로 수집하지는 않습니다(수집은 일일 파이프라인 담당).")

    mg_label = st.radio("시장", ["국장", "미장"], horizontal=True, key="tr_mg")
    market_group = "KR" if mg_label == "국장" else "US"
    currency = "KRW" if market_group == "KR" else "USD"
    st_label = st.radio("상태", ["대기중", "진입", "TP IN", "완료"], horizontal=True, key="tr_st")
    status = _ST_CODE[st_label]

    records = db.list_trade_records(market_group, status)
    if records is None:
        st.warning("⚠️ trade_records 테이블이 아직 없습니다. Supabase SQL Editor에서 아래 SQL을 실행하세요.")
        st.code(TRADE_SQL, language="sql")
        return

    z = lambda v: float(v) if v else None   # 폼의 0 입력은 None(미입력)으로 저장

    # 새 기록 입력 폼
    with st.expander(f"➕ 새 기록 추가 — {mg_label} · {st_label}", expanded=(len(records) == 0)):
        with st.form(f"tr_form_{market_group}_{status}", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            f_date = c1.date_input("날짜", value=dt.date.today())
            f_sym = c2.text_input("티커 (본주)", placeholder="예: 005490 / NVDA")
            f_lev = c3.text_input("레버리지 ETF명(티커)", placeholder="예: TQQQ, NVDL")
            e1, e2, e3, e4 = st.columns(4)
            f_e1 = e1.number_input("1차 진입", min_value=0.0, key=None)
            f_e2 = e2.number_input("2차 진입", min_value=0.0)
            f_e3 = e3.number_input("3차 진입", min_value=0.0)
            f_e4 = e4.number_input("4차 진입", min_value=0.0)
            t1, t2, t3 = st.columns(3)
            f_tp1 = t1.number_input("1차 익절", min_value=0.0)
            f_tp2 = t2.number_input("2차 익절", min_value=0.0)
            f_stop = t3.number_input("손절가", min_value=0.0)
            r1, r2, r3, r4 = st.columns(4)
            f_r1 = r1.number_input("1차 리스크", min_value=0.0)
            f_r2 = r2.number_input("2차 리스크", min_value=0.0)
            f_r3 = r3.number_input("3차 리스크", min_value=0.0)
            f_r4 = r4.number_input("4차 리스크", min_value=0.0)
            f_memo = st.text_input("메모", "")
            f_p1 = f_p2 = f_p3 = f_ps = 0.0
            if status == "tp_in":
                p1c, p2c = st.columns(2)
                f_p1 = p1c.number_input("1차 익절 금액", value=0.0)
                f_p2 = p2c.number_input("2차 익절 금액", value=0.0)
            elif status == "completed":
                p1c, p2c, p3c, p4c = st.columns(4)
                f_p1 = p1c.number_input("1차 익절 금액", value=0.0)
                f_p2 = p2c.number_input("2차 익절 금액", value=0.0)
                f_p3 = p3c.number_input("3차 익절 금액", value=0.0)
                f_ps = p4c.number_input("손절액 (양수 입력)", value=0.0)
                st.caption("총 손익은 저장 시 자동 계산: 1차+2차+3차 − |손절액|")
            if st.form_submit_button("💾 저장"):
                if not f_sym.strip():
                    st.error("티커를 입력하세요.")
                else:
                    rec = {
                        "market_group": market_group, "status": status,
                        "record_date": f_date.isoformat(),
                        "symbol": normalize_symbol(f_sym, market_group),   # KR 숫자코드 6자리 보정
                        "leverage_symbol": normalize_symbol(f_lev, market_group) or None,
                        "entry1": z(f_e1), "entry2": z(f_e2), "entry3": z(f_e3), "entry4": z(f_e4),
                        "tp1": z(f_tp1), "tp2": z(f_tp2), "stop": z(f_stop),
                        "risk1": z(f_r1), "risk2": z(f_r2), "risk3": z(f_r3), "risk4": z(f_r4),
                        "realized_tp1_profit": f_p1 if f_p1 else None,
                        "realized_tp2_profit": f_p2 if f_p2 else None,
                        "realized_tp3_profit": f_p3 if f_p3 else None,
                        "realized_stop_loss": f_ps if f_ps else None,
                        "realized_total_pnl": (calc_total_pnl(f_p1, f_p2, f_p3, f_ps)
                                               if status == "completed" and any((f_p1, f_p2, f_p3, f_ps))
                                               else None),
                        "memo": f_memo.strip() or None,
                    }
                    try:
                        db.upsert_trade_record(rec)
                        st.toast(f"{rec['symbol']} 기록 저장됨")
                        st.rerun()
                    except Exception as e:
                        st.error(f"저장 실패: {e}")

    # 매매기록 검색 — 현재 국장/미장·상태 필터 결과 내 로컬 필터링(read-only).
    # record id 기반 관리(수정/삭제/상태변경)는 필터된 목록에서도 id가 그대로라 안전.
    tq = st.text_input("매매기록 검색", key="tr_q",
                       placeholder="티커·종목명·ETF·메모·날짜")
    tr_searched = bool(normalize_search_query(tq))
    if records and tr_searched:
        _nm = stock_name_map()
        records = [x for x in records if trade_matches_query(x, tq, _nm)]

    # 기록 카드 목록 (모바일 가독성 — 표 대신 카드 + 상세 expander)
    if records:
        st.caption("레버리지 ETF 입력 시: 환산가 = ETF 현재가 × (1 + 본주 변동률 × 2). "
                   "ETF 미입력(본주 매매) 시: 환산가 = 본주 가격 그대로. "
                   "수량 = 리스크 ÷ (진입환산 − 손절환산), 일반 반올림 · 계획 표시용")
        for r in records:
            _render_trade_card(r, currency)
    else:
        st.info("현재 조건에서 일치하는 매매기록이 없습니다." if tr_searched
                else f"{mg_label} · {st_label} 기록이 없습니다. 위에서 추가하세요.")

    # 기록 관리(상태 변경 / 삭제 / 완료 손익 수동 입력)
    if records:
        st.divider()
        st.markdown("**기록 관리**")
        opts = {f"{r['record_date']} {r['symbol']} ({str(r['id'])[:8]})": r for r in records}
        sel = st.selectbox("기록 선택", list(opts.keys()), key=f"tr_sel_{market_group}_{status}")
        r = opts[sel]
        m1, m2, m3 = st.columns([1.4, 1, 1])
        new_label = m1.selectbox("상태 변경", list(_ST_CODE.keys()),
                                 index=list(_ST_CODE.keys()).index(st_label),
                                 key=f"tr_ns_{market_group}_{status}")
        if m2.button("상태 적용", key=f"tr_apply_{market_group}_{status}"):
            try:
                db.upsert_trade_record({"id": r["id"], "status": _ST_CODE[new_label]})
                st.toast(f"{r['symbol']} → {new_label}")
                st.rerun()
            except Exception as e:
                st.error(f"상태 변경 실패: {e}")
        if m3.button("🗑 삭제", key=f"tr_del_{market_group}_{status}"):
            try:
                db.delete_trade_record(r["id"])
                st.toast(f"{r['symbol']} 기록 삭제됨")
                st.rerun()
            except Exception as e:
                st.error(f"삭제 실패: {e}")

        # 선택 기록 수정 — 기존값 prefill, id 기준 update (모바일 고려해 expander로 접음)
        with st.expander(f"✏️ 선택 기록 수정 — {r.get('record_date')} {r.get('symbol')}"):
            def _f(k):
                v = r.get(k)
                return float(v) if v is not None else 0.0
            try:
                _d0 = dt.date.fromisoformat(str(r.get("record_date")))
            except (ValueError, TypeError):
                _d0 = dt.date.today()
            with st.form(f"tr_edit_{r['id']}"):
                c1, c2, c3 = st.columns(3)
                g_date = c1.date_input("날짜", value=_d0)
                g_sym = c2.text_input("티커 (본주)", value=r.get("symbol") or "")
                g_lev = c3.text_input("레버리지 ETF명(티커)", value=r.get("leverage_symbol") or "")
                e1, e2, e3, e4 = st.columns(4)
                g_e1 = e1.number_input("1차 진입", min_value=0.0, value=_f("entry1"))
                g_e2 = e2.number_input("2차 진입", min_value=0.0, value=_f("entry2"))
                g_e3 = e3.number_input("3차 진입", min_value=0.0, value=_f("entry3"))
                g_e4 = e4.number_input("4차 진입", min_value=0.0, value=_f("entry4"))
                t1c, t2c, t3c = st.columns(3)
                g_tp1 = t1c.number_input("1차 익절", min_value=0.0, value=_f("tp1"))
                g_tp2 = t2c.number_input("2차 익절", min_value=0.0, value=_f("tp2"))
                g_stop = t3c.number_input("손절가", min_value=0.0, value=_f("stop"))
                r1c, r2c, r3c, r4c = st.columns(4)
                g_r1 = r1c.number_input("1차 리스크", min_value=0.0, value=_f("risk1"))
                g_r2 = r2c.number_input("2차 리스크", min_value=0.0, value=_f("risk2"))
                g_r3 = r3c.number_input("3차 리스크", min_value=0.0, value=_f("risk3"))
                g_r4 = r4c.number_input("4차 리스크", min_value=0.0, value=_f("risk4"))
                g_memo = st.text_input("메모", value=r.get("memo") or "")
                g_p1, g_p2 = _f("realized_tp1_profit"), _f("realized_tp2_profit")
                g_p3, g_ps = _f("realized_tp3_profit"), _f("realized_stop_loss")
                if r.get("status") == "tp_in":
                    p1c, p2c = st.columns(2)
                    g_p1 = p1c.number_input("1차 익절 금액", value=g_p1)
                    g_p2 = p2c.number_input("2차 익절 금액", value=g_p2)
                elif r.get("status") == "completed":
                    p1c, p2c, p3c, p4c = st.columns(4)
                    g_p1 = p1c.number_input("1차 익절 금액", value=g_p1)
                    g_p2 = p2c.number_input("2차 익절 금액", value=g_p2)
                    g_p3 = p3c.number_input("3차 익절 금액", value=g_p3)
                    g_ps = p4c.number_input("손절액 (양수 입력)", value=g_ps)
                    st.caption("총 손익은 저장 시 자동 계산: 1차+2차+3차 − |손절액| "
                               "(손익을 입력하지 않으면 기존 총 손익 유지)")
                if st.form_submit_button("💾 수정 저장"):
                    if not g_sym.strip():
                        st.error("티커를 입력하세요.")
                    else:
                        payload = {
                            "id": r["id"],
                            "record_date": g_date.isoformat(),
                            "symbol": normalize_symbol(g_sym, r.get("market_group")),
                            "leverage_symbol": normalize_symbol(g_lev, r.get("market_group")) or None,
                            "entry1": z(g_e1), "entry2": z(g_e2), "entry3": z(g_e3), "entry4": z(g_e4),
                            "tp1": z(g_tp1), "tp2": z(g_tp2), "stop": z(g_stop),
                            "risk1": z(g_r1), "risk2": z(g_r2), "risk3": z(g_r3), "risk4": z(g_r4),
                            "realized_tp1_profit": g_p1 if g_p1 else None,
                            "realized_tp2_profit": g_p2 if g_p2 else None,
                            "realized_tp3_profit": g_p3 if g_p3 else None,
                            "realized_stop_loss": g_ps if g_ps else None,
                            "memo": g_memo.strip() or None,
                        }
                        # 총 손익: 완료 상태에서 손익을 하나라도 입력한 경우에만 자동 계산해 저장.
                        # (기존 completed 기록의 total만 있고 세부가 빈 경우 — 미입력 저장 시 기존값 보존)
                        if r.get("status") == "completed" and any((g_p1, g_p2, g_p3, g_ps)):
                            payload["realized_total_pnl"] = calc_total_pnl(g_p1, g_p2, g_p3, g_ps)
                        try:
                            db.upsert_trade_record(payload)
                            st.toast(f"{payload['symbol']} 기록 수정됨")
                            st.rerun()
                        except Exception as e:
                            st.error(f"수정 실패: {e}")

        if status in ("tp_in", "completed"):
            st.caption("실현 손익 입력 — 총 손익은 자동 계산(1차+2차+3차 − |손절액|), 손절액은 양수 입력 권장")
            if status == "tp_in":
                q1, q2 = st.columns(2)
                v1 = q1.number_input("1차 익절 금액", value=float(r.get("realized_tp1_profit") or 0.0),
                                     key=f"tr_p1_{r['id']}")
                v2 = q2.number_input("2차 익절 금액", value=float(r.get("realized_tp2_profit") or 0.0),
                                     key=f"tr_p2_{r['id']}")
                v3 = float(r.get("realized_tp3_profit") or 0.0)
                v4 = float(r.get("realized_stop_loss") or 0.0)
            else:
                q1, q2, q3, q4, q5 = st.columns([1, 1, 1, 1, 1])
                v1 = q1.number_input("1차 익절 금액", value=float(r.get("realized_tp1_profit") or 0.0),
                                     key=f"tr_p1_{r['id']}")
                v2 = q2.number_input("2차 익절 금액", value=float(r.get("realized_tp2_profit") or 0.0),
                                     key=f"tr_p2_{r['id']}")
                v3 = q3.number_input("3차 익절 금액", value=float(r.get("realized_tp3_profit") or 0.0),
                                     key=f"tr_p3v_{r['id']}")
                v4 = q4.number_input("손절액 (양수 입력)", value=float(r.get("realized_stop_loss") or 0.0),
                                     key=f"tr_p4v_{r['id']}")
                q5.metric("총 손익(자동)", f"{calc_total_pnl(v1, v2, v3, v4):,.0f}")
            if st.button("💾 손익 저장", key=f"tr_psave_{r['id']}"):
                payload = {"id": r["id"],
                           "realized_tp1_profit": v1 or None,
                           "realized_tp2_profit": v2 or None}
                if status == "completed":
                    payload["realized_tp3_profit"] = v3 or None
                    payload["realized_stop_loss"] = v4 or None
                    if any((v1, v2, v3, v4)):
                        payload["realized_total_pnl"] = calc_total_pnl(v1, v2, v3, v4)
                try:
                    db.upsert_trade_record(payload)
                    st.toast("손익 저장됨")
                    st.rerun()
                except Exception as e:
                    st.error(f"손익 저장 실패: {e}")


def main():
    if not gate():
        return

    stocks, history, last_update, last_date = load_data()

    # 관심가(stock_targets)를 세션에 1회 시드 — 이후 저장/해제로 in-place 갱신.
    # 조회 실패해도 get_targets()가 {} 반환하므로 화면은 유지된다.
    if "targets" not in st.session_state:
        st.session_state["targets"] = db.get_targets()

    # 상단 고정: 마지막 최신화 시각(메뉴 9) + 데이터 기준일 — 상세 요약은 홈 탭으로 이동
    st.caption(f"🕒 마지막 최신화: {last_update or '아직 갱신 전'} · 기준일 {last_date or '—'}"
               " · 읽기 전용 (갱신은 매 거래일 16:40 자동)")

    if len(stocks) == 0:
        st.info("아직 데이터가 없습니다. update.py가 한 번 실행되면 채워집니다.")
        return

    # 통합 검색 — 전체 종목(188) + 전 상태 매매기록. read-only 로컬 필터링.
    gq = st.text_input("🔎 전체 종목·매매기록 검색", key="global_q",
                       placeholder="예: NVDA · 파두 · 5930 · 메모 키워드")
    if normalize_search_query(gq):
        ranks = stocks.apply(lambda r: stock_match_rank(r, gq), axis=1)
        hits = stocks[ranks.notna()].copy()
        if len(hits):
            hits["__rank"] = ranks[ranks.notna()]
            hits = hits.sort_values("__rank")
        tmap = stock_name_map()
        t_hits = [t for t in load_all_trades() if trade_matches_query(t, gq, tmap)]
        t_hits.sort(key=lambda r: str(r.get("record_date") or ""), reverse=True)
        st.markdown(f"**검색 결과 — 종목 {len(hits)}개 · 매매기록 {len(t_hits)}개**")
        if len(hits):
            sdf = pd.DataFrame([{
                "종목명": h.get("name"), "코드": h.get("code"), "시장": h.get("market"),
                "현재가": format_price(h.get("close"), get_currency(h)) if h.get("close") is not None and not pd.isna(h.get("close")) else "—",
                "현재섹터": current_sector(h),
            } for h in hits.to_dict("records")])
            st.dataframe(sdf, use_container_width=True, hide_index=True)
        if t_hits:
            tdf = pd.DataFrame([{
                "날짜": t.get("record_date"),
                "상태": _ST_LABEL.get(t.get("status"), t.get("status")),
                "시장": "국장" if t.get("market_group") == "KR" else "미장",
                "티커": t.get("symbol"), "ETF": t.get("leverage_symbol") or "—",
                "메모": t.get("memo") or "",
            } for t in t_hits])
            st.dataframe(tdf, use_container_width=True, hide_index=True)
        if not len(hits) and not t_hits:
            st.info("일치하는 종목·매매기록이 없습니다.")
        st.divider()

    # 최상위 내비게이션 4탭 — 구 사이드바 필터는 섹터/더보기 화면 내부 expander로 이동,
    # 구 9탭 화면은 삭제 없이 섹터/더보기 하위 메뉴로 재배치.
    tabs = st.tabs(["홈", "섹터", "매매", "더보기"])

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

    # 1) 홈 — 최소 요약만 (종목 카드는 섹터 탭, 매매기록은 매매 탭)
    with tabs[0]:
        total_swing = int((stocks["classification"] == "swing").sum()) if len(stocks) else 0
        counts = {"waiting": 0, "entered": 0, "tp_in": 0}
        for t in load_all_trades():
            s = t.get("status")
            if s in counts:
                counts[s] += 1
        with st.container(border=True):
            h1, h2, h3 = st.columns(3)
            h1.metric("전체 종목", len(stocks))
            h2.metric("단기스윙", total_swing)
            h3.metric("진행 중 매매", sum(counts.values()))
            chips = (_badge(f"대기중 {counts['waiting']}", "#E5E7EB", "#374151")
                     + _badge(f"진입 {counts['entered']}", "#DBEAFE", "#1D4ED8")
                     + _badge(f"TP IN {counts['tp_in']}", "#FEF3C7", "#92400E"))
            st.markdown(f"<div class='zp-card'>{chips}</div>", unsafe_allow_html=True)
        st.caption("종목 카드는 **섹터** 탭, 매매기록 관리는 **매매** 탭, 표·이력·CSV는 **더보기** 탭에 있습니다.")

    # 2) 섹터 — 메뉴형 섹터맵: 메뉴(전체/단기스윙/기존 섹터) 선택 → 종목을 상세 카드로
    with tabs[1]:
        apply_sec = render_filters(stocks, "sec", with_search=False)
        base = apply_sec(stocks).copy()
        base["__cat"] = cur_cat_series(base)
        order_key = lambda c: (c != "단기스윙", c == "확인 보류", str(c))
        cats_all = sorted(base["__cat"].dropna().unique(), key=order_key)
        menu = ["전체"] + cats_all
        default_idx = menu.index("단기스윙") if "단기스윙" in menu else 0
        choice = select_pills("섹터 메뉴", menu, default_idx=default_idx, key="sector_menu")
        # 메뉴 범위 내 로컬 검색 (read-only)
        local_q = st.text_input("이 메뉴에서 종목 검색", key="sector_q",
                                placeholder="이름·코드 (예: 파두, 5930)")
        sec_searched = bool(normalize_search_query(local_q))

        if choice == "전체":
            sub = base
        else:
            sub = base[base["__cat"] == choice]
        if sec_searched:
            sub = filter_stocks_by_query(sub, local_q)
        if choice == "전체":
            title = f"📂 전체 — {len(sub)}종목"
        else:
            label = "🔹 단기스윙 (1,000억 이하 · 섹터 통합)" if choice == "단기스윙" else f"🗂 {choice}"
            title = f"{label} — {len(sub)}종목"
        st.subheader(title)
        st.divider()

        if sub.empty:
            st.info("이 메뉴에서 일치하는 종목이 없습니다." if sec_searched
                    else "해당 메뉴에 표시할 종목이 없습니다. (사이드바 필터를 확인하세요)")
        else:
            if len(sub) > 60:
                st.caption(f"종목이 많아({len(sub)}개) 로딩이 다소 걸릴 수 있어요. 메뉴로 좁혀 보세요.")
            for rec in sub.to_dict("records"):
                render_stock_card(rec, keyns="map")

        csv_download(base.drop(columns="__cat").assign(현재섹터=cur_cat_series(base)),
                     "⬇ 섹터구성 CSV (단기스윙 포함)", "zpick_categories.csv")

    # 3) 매매 — 국장/미장 × 대기중/진입/TP IN/완료 + 레버리지 환산(2배 고정)
    with tabs[2]:
        render_trade_tab()

    # 4) 더보기 — 저빈도 조회 화면(구 탭 7종)을 하위 메뉴로 재배치 (기능 삭제 없음)
    with tabs[3]:
        more_menu = ["전체 종목", "단기스윙", "거래대금 순위", "신규 편입",
                     "분류 이탈", "변경 이력", "확인 보류"]
        m_choice = select_pills("더보기 메뉴", more_menu, default_idx=0, key="more_menu")

        # 종목 표 화면에만 필터 노출 (구 사이드바 검색 필드 포함 — 이 화면엔 자체 검색이 없음)
        apply_more = None
        if m_choice in ("전체 종목", "단기스윙", "거래대금 순위"):
            apply_more = render_filters(stocks, "more", with_search=True)

        if m_choice == "전체 종목":
            d = apply_more(stocks)
            st.dataframe(view(d), use_container_width=True, hide_index=True)
            csv_download(d, "⬇ 전체 CSV", "zpick_all.csv")

        elif m_choice == "단기스윙":
            d = apply_more(stocks[stocks["classification"] == "swing"])
            st.dataframe(view(d), use_container_width=True, hide_index=True)
            csv_download(d, "⬇ 단기스윙 CSV", "zpick_swing.csv")

        elif m_choice == "거래대금 순위":
            d = stocks.dropna(subset=["avg_6m"]).sort_values("avg_6m", ascending=False)
            d = apply_more(d)
            st.dataframe(view(d), use_container_width=True, hide_index=True)

        elif m_choice == "신규 편입":
            if len(history):
                today = last_date
                ne = history[(history["change_date"] == today) &
                             (history["to_class"] == "단기스윙")]
                st.dataframe(ne, use_container_width=True, hide_index=True)
                if len(ne) == 0:
                    st.info("오늘 신규 편입 종목이 없습니다.")
            else:
                st.info("이력이 아직 없습니다.")

        elif m_choice == "분류 이탈":
            if len(history):
                today = last_date
                ex = history[(history["change_date"] == today) &
                             (history["to_class"] == "기존섹터")]
                st.dataframe(ex, use_container_width=True, hide_index=True)
                if len(ex) == 0:
                    st.info("오늘 분류 이탈 종목이 없습니다.")
            else:
                st.info("이력이 아직 없습니다.")

        elif m_choice == "변경 이력":
            if len(history):
                h = history.copy()
                for col in ("prev_avg_6m", "new_avg_6m"):
                    if col in h.columns:
                        h[col] = h[col].apply(eok)
                st.dataframe(h, use_container_width=True, hide_index=True)
                csv_download(history, "⬇ 이력 CSV", "zpick_history.csv")
            else:
                st.info("이력이 아직 없습니다.")

        elif m_choice == "확인 보류":
            d = stocks[stocks["classification"] == "hold"]
            cols = [c for c in ["name","code","market","origin_sector","reason","data_date"] if c in d.columns]
            st.dataframe(d[cols].rename(columns={
                "name":"종목명","code":"코드","market":"시장",
                "origin_sector":"기존섹터","reason":"사유","data_date":"기준일"}),
                use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
