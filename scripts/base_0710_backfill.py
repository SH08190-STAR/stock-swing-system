"""base_0710_backfill.py — 미국 본주 29개의 2026-07-10 단일일 보정 (ETF 백필과 분리).

배경: 기존 파이프라인이 FDR end-exclusive 때문에 최신 완료 거래일(2026-07-10)을 한 거래일
누락시켜, 워치리스트 US 본주 29개가 07-09에서 멈췄다(ETF는 백필로 07-10 보유). 이 스크립트는
그 29개 본주에 2026-07-10 행만 보정 insert 한다.

안전 원칙 (엄수):
- 이 스크립트의 allowlist = 아래 29개 US 본주 code뿐(39-code ETF 백필 allowlist와 분리).
- 날짜는 정확히 2026-07-10 하루. 다른 date는 절대 insert하지 않는다.
- prices 테이블만 write. 기존에 없는 (code, 2026-07-10) 키만 plain insert(upsert/overwrite/update 금지).
- ETF 행·allowlist 밖 심볼 write 금지. stocks/trade_records/stock_targets 무접촉.
- 공급자 원본에 07-10이 없으면 해당 code 실패 처리(가짜 값 저장 안 함).
- 기본 dry-run. 실제 write는 --execute 필수. 롤백 SQL은 삽입 키만 삭제하도록 준비만.

사용:
  py -3.12 scripts/base_0710_backfill.py manifest            # 읽기 전용, 계획·manifest 저장
  py -3.12 scripts/base_0710_backfill.py canary  --execute   # AAPL, NVDA만 insert
  py -3.12 scripts/base_0710_backfill.py full    --execute   # 나머지 27개 insert
"""
from __future__ import annotations
import sys, os, json, argparse
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import database as db, collector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, ".tmp", "quote_pair_base_0710_manifest.json")
ROLLBACK_SQL = os.path.join(ROOT, ".tmp", "quote_pair_base_0710_rollback.sql")

TARGET_DATE = dt.date(2026, 7, 10)
CANARY = ["AAPL", "NVDA"]

# 진단(2026-07-13)에서 확정된 2026-07-10 누락 US 본주 고유 code 29개. 이 목록만 대상.
CODES_29 = [
    "AAPL", "AMZN", "ANET", "AVGO", "BA", "COIN", "EOSE", "GOOGL", "HOOD", "LUNR",
    "META", "MRVL", "MSFT", "NOW", "NVDA", "NVO", "OKLO", "ORCL", "PLTR", "PLUG",
    "RKLB", "SMCI", "SNDK", "SNOW", "TEM", "TER", "TSLA", "UMAC", "UNH",
]


def total_prices_count() -> int:
    return db.client().table("prices").select("code", count="exact").limit(1).execute().count or 0


def has_0710(code: str) -> bool:
    r = (db.client().table("prices").select("date").eq("code", code)
         .eq("date", TARGET_DATE.isoformat()).limit(1).execute())
    return bool(r.data)


def provider_0710_row(code: str):
    """공급자(FDR, end 보정 적용)에서 2026-07-10 행만 추출. 없으면 None."""
    df = collector.fetch_fdr_through(code, dt.date(2026, 7, 1), TARGET_DATE)
    if df is None or len(df) == 0:
        return None
    for ix, r in df.iterrows():
        d = ix.date() if hasattr(ix, "date") else ix
        if d == TARGET_DATE:
            return {
                "code": code, "market": "", "date": TARGET_DATE.isoformat(),
                "close": db._num(r.get("close")), "high": db._num(r.get("high")),
                "volume": db._num(r.get("volume")), "value": db._num(r.get("value")),
                "value_estimated": bool(r.get("value_estimated", True)),
            }
    return None


def build_manifest():
    codes_info, planned = [], []
    for code in CODES_29:
        exists = has_0710(code)
        row = None if exists else provider_0710_row(code)
        will_insert = (not exists) and row is not None
        codes_info.append({
            "code": code, "existing_0710": exists,
            "provider_0710_price": (row or {}).get("close") if row else None,
            "insert_key": f"{code}|{TARGET_DATE.isoformat()}" if will_insert else None,
            "status": ("이미 있음(skip)" if exists else
                       ("삽입 예정" if will_insert else "공급자 07-10 없음(실패)")),
        })
        if will_insert:
            planned.append(f"{code}|{TARGET_DATE.isoformat()}")
    manifest = {
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "task": "US base single-day correction (2026-07-10)",
        "separate_from": "39-code ETF backfill allowlist",
        "target_table": "prices", "write_mode": "plain insert (NO upsert)",
        "target_date": TARGET_DATE.isoformat(),
        "allowlist_codes": CODES_29, "allowlist_count": len(CODES_29),
        "codes": codes_info,
        "planned_insert_keys": planned, "planned_insert_count": len(planned),
        "total_prices_before": total_prices_count(),
        "other_tables_before": {t: db.client().table(t).select("*", count="exact").limit(1).execute().count
                                for t in ("trade_records", "stocks", "stock_targets")},
        "canary_done": False, "inserted_keys": [],
    }
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return manifest


def _load():
    with open(MANIFEST, encoding="utf-8") as f:
        return json.load(f)


def _save(m):
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)


def _write_rollback_sql(m):
    keys = m.get("inserted_keys", [])
    if not keys:
        return
    pairs = ",\n  ".join(f"('{k.split('|')[0]}','{k.split('|')[1]}')" for k in keys)
    sql = ("-- base_0710 롤백 (준비만 — 실행 금지). 실제 삽입된 (code,2026-07-10) 키만 삭제.\n"
           f"-- 삽입 키 수: {len(keys)}. code 전체/날짜 범위 삭제 금지.\n"
           "delete from prices where (code, date) in (\n  " + pairs + "\n);\n")
    with open(ROLLBACK_SQL, "w", encoding="utf-8") as f:
        f.write(sql)


def _execute(target_codes, label, execute: bool):
    m = _load()
    allow = set(m["allowlist_codes"])
    inserted, failed, skipped = {}, [], []
    for code in target_codes:
        if code not in allow:
            skipped.append({"code": code, "reason": "allowlist 밖"}); continue
        if has_0710(code):
            skipped.append({"code": code, "reason": "07-10 이미 있음"}); continue
        row = provider_0710_row(code)
        if row is None:
            failed.append({"code": code, "reason": "공급자 07-10 없음"}); continue
        if row["date"] != TARGET_DATE.isoformat():         # 방어: 07-10 외 저장 금지
            failed.append({"code": code, "reason": "date != 07-10"}); continue
        try:
            if execute:
                db.client().table("prices").insert([row]).execute()   # plain insert 1행
            inserted[code] = f"{code}|{TARGET_DATE.isoformat()}"
            print(f"  [{label}] {code}: {'insert' if execute else 'DRY'} 1행 (07-10 close={row['close']})")
        except Exception as e:
            failed.append({"code": code, "reason": f"{type(e).__name__}: {e}"})
            print(f"  [{label}] {code}: 실패 {type(e).__name__}")
    return m, inserted, failed, skipped


def run_manifest():
    m = build_manifest()
    print(f"allowlist(US 본주): {m['allowlist_count']}개 (39-code ETF 백필과 분리)")
    print(f"삽입 예정: {m['planned_insert_count']}, 목표일: {m['target_date']}")
    fails = [c["code"] for c in m["codes"] if "실패" in c["status"]]
    skips = [c["code"] for c in m["codes"] if "skip" in c["status"]]
    print(f"  이미 있음(skip): {skips or '없음'}")
    print(f"  공급자 07-10 없음(실패): {fails or '없음'}")
    print(f"prices 총행수(실행 전): {m['total_prices_before']}, manifest: {MANIFEST}")
    return 0


def run_canary(execute: bool):
    before = total_prices_count()
    m, inserted, failed, skipped = _execute(CANARY, "canary", execute)
    after = total_prices_count()
    if execute:
        m["inserted_keys"].extend(inserted.values())
        m["canary_done"] = True; m["canary_codes"] = CANARY
        m["canary_inserted"] = inserted; m["total_prices_after_canary"] = after
        _save(m); _write_rollback_sql(m)
    print(f"canary {'삽입' if execute else 'DRY'} 행수: {after-before} "
          f"(inserted={list(inserted)}, failed={failed}, skipped={skipped})")
    return 0


def run_full(execute: bool):
    m = _load()
    if execute and not m.get("canary_done"):
        print("STOP: canary 미완료 — full --execute 금지"); return 2
    remaining = [code for code in CODES_29 if code not in set(m.get("canary_codes", []))]
    before = total_prices_count()
    m, inserted, failed, skipped = _execute(remaining, "full", execute)
    after = total_prices_count()
    if execute:
        m["inserted_keys"].extend(inserted.values())
        m["full_inserted"] = inserted; m["full_failed"] = failed; m["full_skipped"] = skipped
        m["total_prices_after_full"] = after
        _save(m); _write_rollback_sql(m)
    print(f"full {'삽입' if execute else 'DRY'} 행수: {after-before}")
    print(f"실패({len(failed)}): {failed or '없음'} / 스킵({len(skipped)}): {skipped or '없음'}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["manifest", "canary", "full"])
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    if args.mode == "manifest":
        sys.exit(run_manifest())
    elif args.mode == "canary":
        sys.exit(run_canary(args.execute))
    else:
        sys.exit(run_full(args.execute))
