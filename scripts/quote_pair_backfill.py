"""quote_pair_backfill.py — 레버리지 ETF 가격 제한 백필 (옵션 A: 누락 최근 날짜만 추가).

배경: 39개 code(레버리지 ETF·워치리스트 밖 본주)는 prices에 이미 이력이 있으나
2026-06-18 부근에서 갱신이 끊겨 있었다. 워치리스트 본주는 최신(예: 2026-07-09).
이 스크립트는 기존 이력을 건드리지 않고 2026-06-19 이후 '누락된 (code,date) 키만'
순수 insert 해 본주·ETF의 최신 공통 거래일을 만든다.

안전 원칙 (엄수):
- allowlist(확정 39개 code) 밖 code는 절대 write하지 않는다.
- prices 테이블만 write. stocks/trade_records/stock_targets 무접촉.
- **upsert 금지.** 기존에 없는 (code,date) 키만 plain insert → 기존 행 overwrite 0.
- 목표 범위에 이미 있는 키는 삽입 대상에서 제외(skip).
- 미래/장중 미완료 날짜 금지: today(KST) 이전 완료 거래일만.
- delete/truncate 없음. 롤백 SQL은 실제 삽입 키만 삭제하도록 준비만 하고 실행하지 않는다.
- 기본 dry-run. 실제 write는 --execute 를 명시해야만 한다. manifest 필수.

사용:
  py -3.12 scripts/quote_pair_backfill.py manifest            # 읽기 전용, 계획·manifest 저장
  py -3.12 scripts/quote_pair_backfill.py canary  --execute   # KR1+US1 신규 키만 insert
  py -3.12 scripts/quote_pair_backfill.py full    --execute   # 나머지 37개 신규 키만 insert
  (--execute 없이 canary/full 실행 시 삽입 예정만 출력하고 write하지 않음)
"""
from __future__ import annotations
import sys, os, json, argparse
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import database as db, collector
import scripts.run_daily_update as up

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, ".tmp", "quote_pair_backfill_manifest.json")
ROLLBACK_SQL = os.path.join(ROOT, ".tmp", "quote_pair_backfill_rollback.sql")
BACKFILL_START = dt.date(2026, 6, 19)   # 기존 데이터(≤2026-06-18) 보존, 이 날짜부터 누락분만


def compute_allowlist():
    """파이프라인과 동일한 대상·해소 로직으로 신규 수집 code 확정 (워치리스트/미해소명 제외)."""
    trade_rows = db.get_active_trade_symbols()
    targets = collector.build_trade_targets(trade_rows)
    already = up.watchlist_collected_codes()
    out, seen = [], set()
    for mg, code in targets:
        fetch_code = code
        if mg == "KR" and not code.isdigit():
            resolved = db.code_by_name(code)
            if resolved:
                fetch_code = str(resolved)
        if fetch_code in already:
            continue
        if mg == "KR" and not fetch_code.isdigit() and up._looks_like_name(fetch_code):
            continue
        if (mg, fetch_code) not in seen:
            seen.add((mg, fetch_code)); out.append({"market_group": mg, "code": fetch_code})
    return out


def total_prices_count() -> int:
    return db.client().table("prices").select("code", count="exact").limit(1).execute().count or 0


def existing_dates(code: str, start: dt.date) -> set:
    """code의 start 이후 기존 prices 날짜(iso 문자열) 집합."""
    res = (db.client().table("prices").select("date").eq("code", str(code))
           .gte("date", start.isoformat()).limit(1000).execute())
    return {r["date"] for r in (res.data or [])}


def code_minmax_count(code: str):
    hi = db.client().table("prices").select("date").eq("code", str(code)).order("date", desc=True).limit(1).execute()
    lo = db.client().table("prices").select("date").eq("code", str(code)).order("date", desc=False).limit(1).execute()
    cnt = db.client().table("prices").select("code", count="exact").eq("code", str(code)).limit(1).execute().count
    return (cnt or 0,
            (lo.data[0]["date"] if lo.data else None),
            (hi.data[0]["date"] if hi.data else None))


def plan_code(code: str, today: dt.date):
    """code의 삽입 예정 (신규) 날짜와 기존 겹침 날짜 계산. (network fetch + DB read, write 없음)
    반환: (new_dates[iso], overlap_dates[iso], df)."""
    df = collector._fetch_fdr(str(code), BACKFILL_START, today)
    if df is None or len(df) == 0:
        return [], [], None
    prov = []
    for ix in df.index:
        d = ix.date() if hasattr(ix, "date") else ix
        if BACKFILL_START <= d < today:          # 미래/오늘(장중) 제외
            prov.append(d.isoformat())
    exist = existing_dates(code, BACKFILL_START)
    new = [d for d in prov if d not in exist]
    overlap = [d for d in prov if d in exist]
    return new, overlap, df


def _rows_for(code: str, df, new_dates: set):
    """df에서 new_dates에 해당하는 행만 prices 스키마로 변환(기존 save_ohlcv와 동일 필드)."""
    rows = []
    for ix, r in df.iterrows():
        d = ix.date() if hasattr(ix, "date") else ix
        if d.isoformat() not in new_dates:
            continue
        rows.append({
            "code": str(code), "market": "", "date": d.isoformat(),
            "close": db._num(r.get("close")), "high": db._num(r.get("high")),
            "volume": db._num(r.get("volume")), "value": db._num(r.get("value")),
            "value_estimated": bool(r.get("value_estimated", True)),
        })
    return rows


def build_manifest():
    today = dt.date.today()
    allow = compute_allowlist()
    codes_info = []
    total_new = 0
    for r in allow:
        code = r["code"]
        cnt, lo, hi = code_minmax_count(code)
        new, overlap, _df = plan_code(code, today)
        total_new += len(new)
        codes_info.append({
            "market_group": r["market_group"], "code": code,
            "existing_count": cnt, "existing_min": lo, "existing_max": hi,
            "insert_keys": [f"{code}|{d}" for d in new],
            "insert_count": len(new),
            "overlap_existing_keys": [f"{code}|{d}" for d in overlap],
        })
    manifest = {
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "strategy": "option-A: insert missing (code,date) keys only; preserve existing rows",
        "target_table": "prices",
        "write_mode": "plain insert (NO upsert/overwrite)",
        "backfill_start": BACKFILL_START.isoformat(),
        "upper_bound_exclusive_today": today.isoformat(),
        "codes": codes_info,
        "code_count": len(allow),
        "planned_insert_total": total_new,
        "total_prices_before": total_prices_count(),
        "canary_done": False,
        "inserted_keys": [],
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
    """실제 삽입된 키만 삭제하는 롤백 SQL 생성(실행하지 않음). 날짜/코드 전체 삭제 금지."""
    keys = m.get("inserted_keys", [])
    if not keys:
        return
    pairs = ",\n  ".join(f"('{k.split('|')[0]}','{k.split('|')[1]}')" for k in keys)
    sql = ("-- quote_pair_backfill 롤백 (준비만 — 실행 금지). 실제 삽입된 키만 삭제.\n"
           "-- 기존(≤2026-06-18) 데이터·타 code·타 테이블은 건드리지 않는다.\n"
           f"-- 삽입 키 수: {len(keys)}\n"
           "delete from prices where (code, date) in (\n  " + pairs + "\n);\n")
    with open(ROLLBACK_SQL, "w", encoding="utf-8") as f:
        f.write(sql)


def _execute_codes(target_codes, label, execute: bool):
    """target_codes: [{"market_group","code"}]. manifest의 insert_keys만 insert(신규 키만)."""
    m = _load()
    allow_codes = {c["code"] for c in m["codes"]}
    info_by_code = {c["code"]: c for c in m["codes"]}
    today = dt.date.fromisoformat(m["upper_bound_exclusive_today"])
    inserted, failed, skipped = {}, [], []
    for r in target_codes:
        code = r["code"]
        if code not in allow_codes:
            skipped.append({"code": code, "reason": "allowlist 밖"}); continue
        planned = set(k.split("|")[1] for k in info_by_code[code]["insert_keys"])
        if not planned:
            skipped.append({"code": code, "reason": "삽입 예정 키 없음"}); continue
        try:
            new, overlap, df = plan_code(code, today)   # 실행 시점 재확인
            new_confirmed = [d for d in new if d in planned]   # manifest에 있던 키만
            if df is None or not new_confirmed:
                skipped.append({"code": code, "reason": "재확인 결과 신규 키 없음"}); continue
            rows = _rows_for(code, df, set(new_confirmed))
            if execute:
                db.client().table("prices").insert(rows).execute()   # plain insert(overwrite 아님)
            inserted[code] = [f"{code}|{d}" for d in new_confirmed]
            print(f"  [{label}] {code}: {'insert' if execute else 'DRY'} {len(rows)}행"
                  + (f" (기존겹침 {len(overlap)} skip)" if overlap else ""))
        except Exception as e:
            failed.append({"code": code, "reason": f"{type(e).__name__}: {e}"})
            print(f"  [{label}] {code}: 실패 {type(e).__name__}: {e}")
    return m, inserted, failed, skipped


def run_manifest():
    m = build_manifest()
    kr = sum(1 for c in m["codes"] if c["market_group"] == "KR")
    print(f"allowlist: {m['code_count']}개 (KR {kr}, US {m['code_count']-kr})")
    print(f"삽입 예정 총 키수: {m['planned_insert_total']}")
    print(f"목표 범위: {m['backfill_start']} ~ < {m['upper_bound_exclusive_today']}")
    print(f"prices 전체 행수(실행 전): {m['total_prices_before']}")
    # 기존 겹침 키(=덮어쓰기 위험) 총합 — 0이어야 안전, 있으면 skip 처리됨
    overlap_total = sum(len(c["overlap_existing_keys"]) for c in m["codes"])
    print(f"목표 범위 기존 겹침 키(자동 skip): {overlap_total}")
    print(f"manifest 저장: {MANIFEST}")
    return 0


def run_canary(execute: bool):
    m = _load()
    kr = next((c for c in m["codes"] if c["market_group"] == "KR" and c["insert_count"] > 0), None)
    us = next((c for c in m["codes"] if c["market_group"] == "US" and c["insert_count"] > 0), None)
    picks = [x for x in (kr, us) if x]
    print(f"canary 대상: {[c['code'] for c in picks]} (execute={execute})")
    before = total_prices_count()
    m, inserted, failed, skipped = _execute_codes(picks, "canary", execute)
    after = total_prices_count()
    if execute:
        for code, keys in inserted.items():
            m["inserted_keys"].extend(keys)
        m["canary_done"] = True
        m["canary_codes"] = [c["code"] for c in picks]
        m["canary_inserted"] = inserted
        m["total_prices_after_canary"] = after
        _save(m); _write_rollback_sql(m)
    print(f"canary {'삽입' if execute else 'DRY'} 행수: {after - before} "
          f"(inserted={ {k: len(v) for k,v in inserted.items()} }, failed={failed}, skipped={skipped})")
    return 0


def run_full(execute: bool):
    m = _load()
    if execute and not m.get("canary_done"):
        print("STOP: canary 미완료 — full --execute 금지"); return 2
    done = set(m.get("canary_codes", []))
    remaining = [{"market_group": c["market_group"], "code": c["code"]}
                 for c in m["codes"] if c["code"] not in done and c["insert_count"] > 0]
    print(f"full 대상(나머지): {len(remaining)} (execute={execute})")
    before = total_prices_count()
    m, inserted, failed, skipped = _execute_codes(remaining, "full", execute)
    after = total_prices_count()
    if execute:
        for code, keys in inserted.items():
            m["inserted_keys"].extend(keys)
        m["full_inserted"] = inserted
        m["full_failed"] = failed
        m["full_skipped"] = skipped
        m["total_prices_after_full"] = after
        _save(m); _write_rollback_sql(m)
    print(f"full {'삽입' if execute else 'DRY'} 행수: {after - before}")
    print(f"실패({len(failed)}): {failed if failed else '없음'}")
    print(f"스킵({len(skipped)}): {skipped if skipped else '없음'}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["manifest", "canary", "full"])
    ap.add_argument("--execute", action="store_true", help="실제 prices insert 수행(기본 dry-run)")
    args = ap.parse_args()
    if args.mode == "manifest":
        sys.exit(run_manifest())
    elif args.mode == "canary":
        sys.exit(run_canary(args.execute))
    else:
        sys.exit(run_full(args.execute))
