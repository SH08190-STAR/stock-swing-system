"""
config.py — 환경설정 및 상수
모든 비밀값(키·토큰·비밀번호)은 환경변수에서만 읽는다. 코드에 하드코딩 금지.
로컬 개발 시 .env 파일을 사용하고, 배포 시에는 각 플랫폼의 Secrets 기능을 쓴다.
"""
import os

try:
    # 로컬 개발 편의: .env 가 있으면 읽어들임 (배포 환경엔 .env 없음)
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


# ── 분류 임계값 ───────────────────────────────────────────────
# 최근 6개월 일평균 거래대금이 이 값 "이하"이면 단기스윙으로 이동.
# 정확히 이 값인 경우도 단기스윙(이하 포함).
SWING_THRESHOLD_KRW = 100_000_000_000  # 1,000억 원

# 6개월 = 약 6개월 전 날짜부터 (실제 거래일 기준으로 평균)
LOOKBACK_MONTHS = 6
# 단기 평균(대시보드 표시용)
SHORT_WINDOW_DAYS = 20


# ── 데이터 소스 ──────────────────────────────────────────────
# 주 소스 실패 시 예비 소스로 폴백
PRIMARY_SOURCE = os.getenv("PRIMARY_SOURCE", "pykrx")        # datagokr | pykrx | fdr
FALLBACK_SOURCE = os.getenv("FALLBACK_SOURCE", "fdr")        # fdr | pykrx
REQUEST_SLEEP_SEC = float(os.getenv("REQUEST_SLEEP_SEC", "0.4"))  # 도의적 호출 간격
MAX_RETRY = int(os.getenv("MAX_RETRY", "3"))

# 공공데이터포털(data.go.kr) 금융위 주식시세정보 API 인증키.
# pykrx/FDR이 거래대금을 주지 않게 된 환경에서 실제 거래대금(trPrc)을 제공하는 공식 공공 API.
# 키가 설정되면 이 소스를 최우선으로 사용한다(없으면 기존 pykrx→fdr 순서).
DATA_GO_KR_KEY = os.getenv("DATA_GO_KR_SERVICE_KEY", "")


# ── Supabase ────────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")  # service_role 또는 anon (쓰기 권한 필요)


# ── 텔레그램 ────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
# 알림 방식 교체용: telegram | discord | email | none
NOTIFY_CHANNEL = os.getenv("NOTIFY_CHANNEL", "telegram")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")


# ── 대시보드 ────────────────────────────────────────────────
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "(배포 후 입력)")
# Streamlit 앱 내 간이 비밀번호(2차 보호). 비우면 비밀번호 화면 생략.
APP_PASSWORD = os.getenv("APP_PASSWORD", "")


# ── 토스 시세 Relay (선택) ───────────────────────────────────
# 본주·레버리지 ETF 현재가 live overlay용. Streamlit은 Toss를 직접 호출하지 않고
# Fly.io Relay(고정 egress IP)를 경유한다. 두 값이 모두 설정된 경우에만 활성화하고,
# 하나라도 없으면 Toss 기능은 조용히 비활성(오류가 아니라 정상 상태 — 기존
# Supabase/FDR 가격 경로를 그대로 사용한다). 실제 값은 출력·repr·로그하지 않는다.
# TOSS_CLIENT_ID/SECRET은 Relay(Fly secrets)에만 존재하며 Streamlit에 넣지 않는다.
# validate_for_collector 필수 목록에 넣지 않는다(수집·인증 gate와 무관).
TOSS_RELAY_URL = os.getenv("TOSS_RELAY_URL", "")
TOSS_RELAY_TOKEN = os.getenv("TOSS_RELAY_TOKEN", "")


def validate_for_collector():
    """수집/저장 실행 전 필수 환경변수 점검. 누락 시 명확한 메시지."""
    missing = []
    if not SUPABASE_URL:
        missing.append("SUPABASE_URL")
    if not SUPABASE_KEY:
        missing.append("SUPABASE_KEY")
    if NOTIFY_CHANNEL == "telegram":
        if not TELEGRAM_BOT_TOKEN:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not TELEGRAM_CHAT_ID:
            missing.append("TELEGRAM_CHAT_ID")
    if missing:
        raise RuntimeError(
            "필수 환경변수 누락: " + ", ".join(missing) +
            "\n.env(로컬) 또는 플랫폼 Secrets에 설정하세요."
        )
