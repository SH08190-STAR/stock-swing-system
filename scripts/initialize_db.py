"""
scripts/initialize_db.py — Supabase 테이블 초기화 안내

Supabase는 SQL Editor에서 schema.sql 실행을 권장한다(권한·트랜잭션 안전).
이 스크립트는 schema.sql 내용을 출력해 복사를 돕고, 연결 점검만 수행한다.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app import config

def main():
    here = os.path.dirname(__file__)
    sql = open(os.path.join(here, "schema.sql"), encoding="utf-8").read()
    print("=== Supabase SQL Editor 에 아래를 붙여넣어 실행하세요 ===\n")
    print(sql)
    # 연결 점검(선택)
    if config.SUPABASE_URL and config.SUPABASE_KEY:
        try:
            from app import database as db
            db.get_meta("last_ok_update")
            print("\n[OK] Supabase 연결 성공")
        except Exception as e:
            print("\n[주의] 연결 점검 실패:", e)
    else:
        print("\n[안내] SUPABASE_URL/KEY 미설정 — .env 설정 후 다시 실행")

if __name__ == "__main__":
    main()
