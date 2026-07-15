# Toss Relay — 토스증권 시세 전용 중계 서비스

## 배경

Streamlit Community Cloud의 outbound IP는 토스 허용 IP 한도(10개)보다 많아
직접 Toss API 호출 구조를 운영에 쓸 수 없다. 대신 **고정 outbound IP를 가진
Fly.io Relay** 1대를 두고, 토스에는 그 static egress IPv4 1개만 등록한다.

```
Streamlit Cloud ──HTTPS──▶ Fly.io Relay (nrt, static egress IPv4)
  (RELAY_URL + RELAY_TOKEN)      └──▶ openapi.tossinvest.com  (허용 IP = egress IPv4 1개)
```

- Toss credentials(TOSS_CLIENT_ID/SECRET)는 **Relay에만** 존재한다.
- Streamlit에는 `TOSS_RELAY_URL` / `TOSS_RELAY_TOKEN` 두 값만 들어간다.
- 시세 조회 전용 — 주문·잔고·계좌 API 접근 기능은 없으며 추가는 별도 승인 필요.

## 공개 API (정확히 2개)

### `GET /healthz` — 인증 불필요, Toss 미호출
```json
{"status": "ok"}
```

### `POST /v1/prices` — `Authorization: Bearer <RELAY_SHARED_SECRET>` 필수
요청 (심볼 1~200개, 문자열만, 심볼당 최대 32자, 그 외 필드 거부):
```json
{"symbols": ["NVDA", "NVDL"]}
```
성공 응답 (`Cache-Control: no-store`, `X-Relay-Api-Version: 1`):
```json
{
  "provider": "Toss",
  "prices": [
    {"symbol": "NVDA", "last_price": "183.42", "currency": "USD",
     "timestamp": "2026-07-15T10:30:00+09:00"}
  ]
}
```
- `last_price`는 Decimal 정밀도 보존을 위한 문자열, `timestamp`는 종목별
  timezone-aware ISO 8601 원본.
- 응답에 없는 심볼은 항목이 생성되지 않는다(호출측 fallback 판단).
- access token·상류 원본 응답은 어떤 경우에도 반환하지 않는다.

### 오류 응답 형식
`{"error": "<code>", "message": "<짧은 고정 문구>"}` — 상류 본문·예외 repr 비포함.

| 상황 | HTTP | error code |
|---|---|---|
| 인증 실패(모든 사유 동일) | 401 | `UNAUTHORIZED` |
| 요청 형식 오류 | 400 | `INVALID_REQUEST` |
| Toss 인증 실패 | 503 | `TOSS_AUTH_FAILED` |
| Toss 접근 거부(허용 IP) | 502 | `TOSS_IP_FORBIDDEN` |
| Toss 호출 한도 초과 | 429 | `TOSS_RATE_LIMITED` (+안전 범위의 `Retry-After`) |
| Toss timeout | 504 | `TOSS_TIMEOUT` |
| Toss 응답 형식 오류 | 502 | `TOSS_BAD_RESPONSE` |
| 기타 Toss 오류 | 502 | `TOSS_UPSTREAM_ERROR` |
| 예상 밖 오류 | 500 | `INTERNAL_ERROR` |

## Secrets (전부 Fly secrets — 코드·이미지·저장소에 절대 미포함)

| 이름 | 용도 |
|---|---|
| `RELAY_SHARED_SECRET` | Relay Bearer 인증 (최소 32자 — 미달 시 시작 실패) |
| `TOSS_CLIENT_ID` | Toss OAuth2 client id |
| `TOSS_CLIENT_SECRET` | Toss OAuth2 client secret |

세 값 중 하나라도 없으면 fail fast로 서비스가 시작되지 않는다.

## 로컬 개발·테스트

```bash
pip install -r services/toss_relay/requirements.txt pytest httpx
pytest tests/test_toss_relay.py -q     # 실제 네트워크 호출 0회 (전부 mock)
```

Docker (빌드 컨텍스트 = 저장소 루트):
```bash
docker build -f services/toss_relay/Dockerfile -t toss-relay .
docker run --rm -p 8080:8080 \
  -e RELAY_SHARED_SECRET="로컬테스트용_32자이상_가짜값_..." \
  -e TOSS_CLIENT_ID="c_FAKE" -e TOSS_CLIENT_SECRET="s_FAKE" \
  toss-relay
curl -s http://127.0.0.1:8080/healthz    # {"status":"ok"} — Toss 미호출
```

## 배포 절차 (향후 수동 — 아직 미실행)

1. Fly 계정·결제수단 준비.
2. `fly auth login` 으로 flyctl 인증.
3. Fly app 생성 (앱 이름 확정 후 `fly.toml.example` → `fly.toml` 복사·수정,
   `fly apps create <APP_NAME>`).
4. Relay secrets 설정 (실값은 이 문서·저장소에 기록하지 않는다):
   ```bash
   fly secrets set --app <APP_NAME> \
     RELAY_SHARED_SECRET=<최소 32자 무작위값> \
     TOSS_CLIENT_ID=<발급값> TOSS_CLIENT_SECRET=<발급값>
   ```
5. 저장소 루트에서 1대만 배포:
   ```bash
   fly deploy . --config services/toss_relay/fly.toml --ha=false
   fly scale count 1 --app <APP_NAME>
   ```
6. static egress IP 할당 (app-scoped, IPv4+IPv6 쌍):
   ```bash
   fly ips allocate-egress --app <APP_NAME> -r nrt
   fly ips list --app <APP_NAME>
   ```
7. 할당된 **egress IPv4 1개만** 토스 허용 IP에 등록.
8. `https://<APP_NAME>.fly.dev/healthz` 200 확인.
9. 인증된 최초 호출은 **테스트 심볼 2개만**:
   ```bash
   curl -s -X POST https://<APP_NAME>.fly.dev/v1/prices \
     -H "Authorization: Bearer $RELAY_SHARED_SECRET" \
     -H "Content-Type: application/json" -d '{"symbols":["NVDA","NVDL"]}'
   ```
10. `fly logs`에서 secret·token이 출력되지 않는지 확인
    (uvicorn access log는 request line·상태코드만 기록).
11. 이후 Streamlit Secrets에는 `TOSS_RELAY_URL`, `TOSS_RELAY_TOKEN` 두 값만 입력.
12. Streamlit에는 `TOSS_CLIENT_ID`/`TOSS_CLIENT_SECRET`을 넣지 않는다.

## 운영 정책

- **static egress IP를 명시적으로 release 하지 않는다**
  (`fly ips release-egress` 금지 — 재할당 시 토스 허용 IP 재등록 필요).
  egress IP는 Machine 파괴·재배포에도 유지되며 명시적 release 때만 사라진다.
- Machine 수는 항상 **최대 1대** (`fly scale count 1`, `--ha=false`).
  2대 이상이면 Toss가 클라이언트당 활성 토큰 1개만 허용하므로 서로 무효화된다.
- uvicorn worker 1개 고정 (Dockerfile CMD) — 프로세스당 TossClient/token 1개.
- staging·production Streamlit이 같은 Relay를 쓰더라도 Relay 내부의 단일
  TossClient/token만 사용된다.
- 주문·계좌 endpoint 추가는 별도 승인 없이는 금지.

## 월 예상 비용 (Fly.io 공식 pricing, 2026-07 기준)

| 항목 | 비용 |
|---|---|
| Machine shared-cpu-1x / 256MB, 상시 1대 | 약 $2/월 (시간당 ~$0.0028, 지역별 소폭 상이) |
| static egress IP (IPv4+IPv6 쌍) | $3.60/월 ($0.005/시간) |
| outbound 데이터 (Asia-Pacific $0.04/GB) | 시세 JSON 수 KB 수준 — 사실상 $0 |
| **합계** | **약 $5.6/월** |

출처: https://fly.io/docs/about/pricing/ , https://fly.io/docs/networking/egress-ips/
