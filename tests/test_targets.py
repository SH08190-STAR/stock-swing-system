"""
tests/test_targets.py — 관심가(stock_targets) DB 함수 검증.
실제 Supabase에 연결하지 않고 client()를 mock으로 대체한다(네트워크 비의존).
"""
from app import database as db


class _Resp:
    def __init__(self, data):
        self.data = data


class _Table:
    """fluent 체인(select/upsert/delete/eq/execute)을 흉내내며 호출을 calls에 기록."""
    def __init__(self, calls, name, data):
        self._calls = calls
        self._name = name
        self._data = data

    def select(self, *a, **k):
        self._calls.append(("select", self._name, a))
        return self

    def upsert(self, payload, on_conflict=None):
        self._calls.append(("upsert", self._name, payload, on_conflict))
        return self

    def delete(self):
        self._calls.append(("delete", self._name))
        return self

    def eq(self, col, val):
        self._calls.append(("eq", col, val))
        return self

    def execute(self):
        return _Resp(self._data)


class _Client:
    def __init__(self, calls, data_by_table=None):
        self._calls = calls
        self._data = data_by_table or {}

    def table(self, name):
        return _Table(self._calls, name, self._data.get(name, []))


def _patch(monkeypatch, data_by_table=None):
    calls = []
    monkeypatch.setattr(db, "client", lambda: _Client(calls, data_by_table))
    return calls


# 1) get_targets: 응답을 {symbol: float} 로 변환
def test_get_targets_maps_to_dict(monkeypatch):
    _patch(monkeypatch, {"stock_targets": [
        {"symbol": "005490", "target_price": 300000},
        {"symbol": "AAPL", "target_price": "190.5"},  # 문자열도 float 변환
    ]})
    out = db.get_targets()
    assert out == {"005490": 300000.0, "AAPL": 190.5}
    assert isinstance(out["005490"], float)


# 2) 빈 응답이면 {}
def test_get_targets_empty(monkeypatch):
    _patch(monkeypatch, {"stock_targets": []})
    assert db.get_targets() == {}


# 2b) 조회 오류 시 {} (안전 처리)
def test_get_targets_error_returns_empty(monkeypatch):
    def boom():
        raise RuntimeError("conn fail")
    monkeypatch.setattr(db, "client", boom)
    assert db.get_targets() == {}


# 3) set_target: 올바른 payload 로 upsert
def test_set_target_upsert_payload(monkeypatch):
    calls = _patch(monkeypatch)
    db.set_target("005490", 305000.0)
    upserts = [c for c in calls if c[0] == "upsert"]
    assert len(upserts) == 1
    _, name, payload, on_conflict = upserts[0]
    assert name == "stock_targets"
    assert payload["symbol"] == "005490"
    assert payload["target_price"] == 305000.0
    assert "updated_at" in payload
    # 4) on_conflict="symbol"
    assert on_conflict == "symbol"
    # upsert 경로에서는 delete 가 호출되지 않아야 함
    assert not any(c[0] == "delete" for c in calls)


# set_target: 0 이하이면 저장 대신 삭제(해제)
def test_set_target_zero_deletes(monkeypatch):
    calls = _patch(monkeypatch)
    db.set_target("AAPL", 0)
    assert not any(c[0] == "upsert" for c in calls)
    assert ("delete", "stock_targets") in calls
    assert ("eq", "symbol", "AAPL") in calls


# 5) delete_target: 올바른 symbol 조건으로 delete
def test_delete_target_calls_delete_eq(monkeypatch):
    calls = _patch(monkeypatch)
    db.delete_target("042700")
    assert ("delete", "stock_targets") in calls
    assert ("eq", "symbol", "042700") in calls
