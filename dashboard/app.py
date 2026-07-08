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


def _fmtp(v, currency):
    return format_price(v, currency) if v is not None else "—"


def _trade_calc(r: dict):
    """기록 1건의 파생값 계산: 현재가·환산가·주당리스크·수량. 표시 전용."""
    base_now = latest_price(r.get("symbol"))
    etf_now = latest_price(r.get("leverage_symbol")) if r.get("leverage_symbol") else None
    conv = lambda t: lev_convert(etf_now, base_now, t)
    stop_lev = conv(r.get("stop"))
    out = {"base_now": base_now, "etf_now": etf_now, "stop_lev": stop_lev, "conv": conv}
    for i in (1, 2, 3, 4):
        e_lev = conv(r.get(f"entry{i}"))
        out[f"e{i}_lev"] = e_lev
        out[f"qty{i}"] = calc_position_qty(e_lev, stop_lev, r.get(f"risk{i}"))
    risks = [r.get(f"risk{i}") for i in (1, 2, 3, 4)]
    out["total_risk"] = sum(float(x) for x in risks if x) or None
    return out


def _summary_table(records: list[dict], status: str, currency: str) -> pd.DataFrame:
    """짧은 요약표(가로 스크롤 최소화). 상세는 아래 expander에서."""
    rows = []
    for r in records:
        c = _trade_calc(r)
        d = {
            "날짜": r.get("record_date"), "티커": r.get("symbol"),
            "ETF": r.get("leverage_symbol") or "—",
            "본주 현재가": _fmtp(c["base_now"], currency),
            "ETF 현재가": _fmtp(c["etf_now"], currency),
            "손절": _fmtp(r.get("stop"), currency),
            "손절 환산": _fmtp(c["stop_lev"], currency),
            "총 계획 리스크": c["total_risk"],
            "메모": r.get("memo") or "",
        }
        if status == "waiting":
            d.update({"1차 진입": _fmtp(r.get("entry1"), currency),
                      "1차 환산": _fmtp(c["e1_lev"], currency),
                      "1차 수량": c["qty1"] if c["qty1"] is not None else "—"})
        elif status == "entered":
            nxt = next((i for i in (2, 3, 4) if r.get(f"entry{i}")), None)
            d.update({
                "다음 진입": _fmtp(r.get(f"entry{nxt}"), currency) if nxt else "—",
                "다음 환산": _fmtp(c[f"e{nxt}_lev"], currency) if nxt else "—",
                "다음 수량": (c[f"qty{nxt}"] if nxt and c[f"qty{nxt}"] is not None else "—"),
                "1차 익절": _fmtp(r.get("tp1"), currency),
                "2차 익절": _fmtp(r.get("tp2"), currency),
            })
        elif status == "tp_in":
            d["2차 익절"] = _fmtp(r.get("tp2"), currency)
        elif status == "completed":
            d["총 손익"] = r.get("realized_total_pnl")
        rows.append(d)
    order = {
        "waiting": ["날짜", "티커", "ETF", "본주 현재가", "ETF 현재가",
                    "1차 진입", "1차 환산", "1차 수량", "손절", "손절 환산", "총 계획 리스크", "메모"],
        "entered": ["날짜", "티커", "ETF", "본주 현재가", "ETF 현재가",
                    "다음 진입", "다음 환산", "다음 수량", "1차 익절", "2차 익절",
                    "손절", "손절 환산", "총 계획 리스크", "메모"],
        "tp_in": ["날짜", "티커", "ETF", "본주 현재가", "ETF 현재가",
                  "2차 익절", "손절", "손절 환산", "총 계획 리스크", "메모"],
        "completed": ["날짜", "티커", "ETF", "본주 현재가", "ETF 현재가",
                      "손절", "손절 환산", "총 계획 리스크", "총 손익", "메모"],
    }[status]
    return pd.DataFrame(rows)[order] if rows else pd.DataFrame(columns=order)


def _render_trade_detail(r: dict, currency: str):
    """기록 1건 상세 expander: 기본정보 / 진입계획(수량) / 익절·손절 / 완료손익."""
    c = _trade_calc(r)
    title = f"{r.get('record_date')} {r.get('symbol')} / {r.get('leverage_symbol') or '—'} / {_ST_LABEL.get(r.get('status'), r.get('status'))}"
    with st.expander(f"📋 {title}"):
        # 1. 기본 정보
        b1, b2, b3, b4 = st.columns(4)
        b1.metric("본주 현재가", _fmtp(c["base_now"], currency))
        b2.metric("ETF 현재가", _fmtp(c["etf_now"], currency))
        b3.metric("시장", "국장" if r.get("market_group") == "KR" else "미장")
        b4.metric("상태", _ST_LABEL.get(r.get("status"), "—"))
        if r.get("memo"):
            st.caption(f"📝 {r['memo']}")

        # 2. 진입 계획 (환산가·주당 리스크·수량)
        plan = []
        for i in (1, 2, 3, 4):
            e, e_lev, risk, qty = r.get(f"entry{i}"), c[f"e{i}_lev"], r.get(f"risk{i}"), c[f"qty{i}"]
            if e is None and risk is None:
                continue
            per = (e_lev - c["stop_lev"]) if (e_lev is not None and c["stop_lev"] is not None) else None
            plan.append({
                "구분": f"{i}차", "본주 진입가": _fmtp(e, currency),
                "ETF 환산가": _fmtp(e_lev, currency),
                "손절 ETF 환산가": _fmtp(c["stop_lev"], currency),
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

        # 4. 완료 손익 (완료 상태만)
        if r.get("status") == "completed":
            st.markdown("**완료 손익 (수동 입력값)**")
            p1, p2, p3, p4 = st.columns(4)
            p1.metric("1차 익절 수익", r.get("realized_tp1_profit") if r.get("realized_tp1_profit") is not None else "—")
            p2.metric("2차 익절 수익", r.get("realized_tp2_profit") if r.get("realized_tp2_profit") is not None else "—")
            p3.metric("손절액", r.get("realized_stop_loss") if r.get("realized_stop_loss") is not None else "—")
            p4.metric("총 손익", r.get("realized_total_pnl") if r.get("realized_total_pnl") is not None else "—")


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
            if status == "completed":
                p1, p2, p3, p4 = st.columns(4)
                f_p1 = p1.number_input("1차 익절 수익", value=0.0)
                f_p2 = p2.number_input("2차 익절 수익", value=0.0)
                f_ps = p3.number_input("손절액", value=0.0)
                f_pt = p4.number_input("총 손익", value=0.0)
            else:
                f_p1 = f_p2 = f_ps = f_pt = 0.0
            if st.form_submit_button("💾 저장"):
                if not f_sym.strip():
                    st.error("티커를 입력하세요.")
                else:
                    rec = {
                        "market_group": market_group, "status": status,
                        "record_date": f_date.isoformat(), "symbol": f_sym.strip().upper(),
                        "leverage_symbol": f_lev.strip().upper() or None,
                        "entry1": z(f_e1), "entry2": z(f_e2), "entry3": z(f_e3), "entry4": z(f_e4),
                        "tp1": z(f_tp1), "tp2": z(f_tp2), "stop": z(f_stop),
                        "risk1": z(f_r1), "risk2": z(f_r2), "risk3": z(f_r3), "risk4": z(f_r4),
                        "realized_tp1_profit": z(f_p1), "realized_tp2_profit": z(f_p2),
                        "realized_stop_loss": f_ps if f_ps else None,
                        "realized_total_pnl": f_pt if f_pt else None,
                        "memo": f_memo.strip() or None,
                    }
                    try:
                        db.upsert_trade_record(rec)
                        st.toast(f"{rec['symbol']} 기록 저장됨")
                        st.rerun()
                    except Exception as e:
                        st.error(f"저장 실패: {e}")

    # 요약표 + 기록별 상세 펼침
    if records:
        st.dataframe(_summary_table(records, status, currency),
                     use_container_width=True, hide_index=True)
        st.caption("환산가 = ETF 현재가 × (1 + 본주 변동률 × 2) · 수량 = 리스크 ÷ (진입환산 − 손절환산), 일반 반올림 · 계획 표시용")
        for r in records:
            _render_trade_detail(r, currency)
    else:
        st.info(f"{mg_label} · {st_label} 기록이 없습니다. 위에서 추가하세요.")

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
                if r.get("status") == "completed":
                    p1c, p2c, p3c, p4c = st.columns(4)
                    g_p1 = p1c.number_input("1차 익절 수익", value=_f("realized_tp1_profit"))
                    g_p2 = p2c.number_input("2차 익절 수익", value=_f("realized_tp2_profit"))
                    g_ps = p3c.number_input("손절액", value=_f("realized_stop_loss"))
                    g_pt = p4c.number_input("총 손익", value=_f("realized_total_pnl"))
                else:
                    g_p1, g_p2, g_ps, g_pt = _f("realized_tp1_profit"), _f("realized_tp2_profit"), \
                        _f("realized_stop_loss"), _f("realized_total_pnl")
                if st.form_submit_button("💾 수정 저장"):
                    if not g_sym.strip():
                        st.error("티커를 입력하세요.")
                    else:
                        payload = {
                            "id": r["id"],
                            "record_date": g_date.isoformat(),
                            "symbol": g_sym.strip().upper(),
                            "leverage_symbol": g_lev.strip().upper() or None,
                            "entry1": z(g_e1), "entry2": z(g_e2), "entry3": z(g_e3), "entry4": z(g_e4),
                            "tp1": z(g_tp1), "tp2": z(g_tp2), "stop": z(g_stop),
                            "risk1": z(g_r1), "risk2": z(g_r2), "risk3": z(g_r3), "risk4": z(g_r4),
                            "realized_tp1_profit": g_p1 if g_p1 else None,
                            "realized_tp2_profit": g_p2 if g_p2 else None,
                            "realized_stop_loss": g_ps if g_ps else None,
                            "realized_total_pnl": g_pt if g_pt else None,
                            "memo": g_memo.strip() or None,
                        }
                        try:
                            db.upsert_trade_record(payload)
                            st.toast(f"{payload['symbol']} 기록 수정됨")
                            st.rerun()
                        except Exception as e:
                            st.error(f"수정 실패: {e}")

        if status == "completed":
            st.caption("완료 손익(1차 MVP: 수동 입력 — 익절 비중 규칙 확정 후 자동화 예정)")
            q1, q2, q3, q4, q5 = st.columns([1, 1, 1, 1, 0.8])
            v1 = q1.number_input("1차 익절 수익", value=float(r.get("realized_tp1_profit") or 0.0),
                                 key=f"tr_p1_{r['id']}")
            v2 = q2.number_input("2차 익절 수익", value=float(r.get("realized_tp2_profit") or 0.0),
                                 key=f"tr_p2_{r['id']}")
            v3 = q3.number_input("손절액", value=float(r.get("realized_stop_loss") or 0.0),
                                 key=f"tr_p3_{r['id']}")
            v4 = q4.number_input("총 손익", value=float(r.get("realized_total_pnl") or 0.0),
                                 key=f"tr_p4_{r['id']}")
            if q5.button("손익 저장", key=f"tr_psave_{r['id']}"):
                try:
                    db.upsert_trade_record({
                        "id": r["id"],
                        "realized_tp1_profit": v1 or None, "realized_tp2_profit": v2 or None,
                        "realized_stop_loss": v3 or None, "realized_total_pnl": v4 or None,
                    })
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
        "매매 기록",
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

    # 9) 매매 기록 — 국장/미장 × 대기중/진입/TP IN/완료 + 레버리지 환산(2배 고정)
    with tabs[8]:
        render_trade_tab()


if __name__ == "__main__":
    main()
