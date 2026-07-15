# Toss Relay — 빌드 컨텍스트는 저장소 루트여야 한다 (app/toss.py 재사용):
#   docker build -f services/toss_relay/Dockerfile -t toss-relay .
# secret은 image에 넣지 않는다 — 전부 런타임 환경변수(Fly secrets)로만 주입.
# base image는 patch·Debian 계열(bookworm)까지 고정해 재현성을 확보한다.
FROM python:3.12.8-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/srv

WORKDIR /srv

# Relay 전용 requirements만 설치 (Streamlit 전체 requirements 미설치, compiler 불필요)
COPY services/toss_relay/requirements.txt ./services/toss_relay/requirements.txt
RUN pip install --no-cache-dir -r services/toss_relay/requirements.txt

# app.toss 재사용에 필요한 최소 파일만 복사
COPY app/__init__.py ./app/__init__.py
COPY app/toss.py ./app/toss.py
COPY services/__init__.py ./services/__init__.py
COPY services/toss_relay/__init__.py ./services/toss_relay/__init__.py
COPY services/toss_relay/config.py ./services/toss_relay/config.py
COPY services/toss_relay/main.py ./services/toss_relay/main.py

RUN useradd --create-home --uid 10001 relay
USER relay

EXPOSE 8080

# worker 1개 고정 — 프로세스당 TossClient/token 1개 보장.
# uvicorn 기본 access log는 request line·상태코드만 기록한다
# (Authorization 헤더·요청 body는 기록되지 않음).
CMD ["python", "-m", "uvicorn", "services.toss_relay.main:create_app", \
     "--factory", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
