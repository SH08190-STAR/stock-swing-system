"""scripts/predeploy_check.py 순수 함수 단위 테스트."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import predeploy_check as pdc  # noqa: E402

# 주의: 샘플 secret 문자열은 predeploy secret 스캔에 걸리지 않도록
# 반드시 문자열 연결로 조립한다 (한 줄에 패턴 원문을 두지 않는다).


def test_find_secrets_detects_aws_key():
    text = "x = '" + "AKIA" + "B" * 16 + "'\n"
    hits = pdc.find_secrets(text)
    assert len(hits) == 1
    assert "AWS" in hits[0]


def test_find_secrets_detects_credential_assignment():
    line = "pass" + 'word = "supersecretvalue1"'
    hits = pdc.find_secrets("a = 1\n" + line + "\n")
    assert len(hits) == 1
    assert hits[0].startswith("line 2")


def test_find_secrets_detects_jwt():
    token = "eyJ" + "a" * 12 + "." + "eyJ" + "b" * 12 + "." + "c" * 12
    assert pdc.find_secrets(token) != []


def test_find_secrets_ignores_normal_code():
    text = "def health_url(base):\n    return base + '/_stcore/health'\n"
    assert pdc.find_secrets(text) == []


def test_iter_scan_targets_parses_porcelain():
    porcelain = (
        " M app/x.py\n"
        "?? new.txt\n"
        " D removed.py\n"
        "R  old.py -> renamed.py\n"
    )
    targets = pdc.iter_scan_targets(porcelain)
    assert targets == ["app/x.py", "new.txt", "renamed.py"]


def test_iter_scan_targets_empty():
    assert pdc.iter_scan_targets("") == []


def test_summarize_and_exit_code_all_pass():
    results = [pdc.CheckResult("a", True, "ok"), pdc.CheckResult("b", True)]
    summary = pdc.summarize(results)
    assert "[PASS] a — ok" in summary
    assert "전체 통과" in summary
    assert pdc.exit_code(results) == 0


def test_summarize_and_exit_code_with_failure():
    results = [pdc.CheckResult("a", True), pdc.CheckResult("b", False, "bad")]
    summary = pdc.summarize(results)
    assert "[FAIL] b — bad" in summary
    assert "실패 항목 있음" in summary
    assert pdc.exit_code(results) == 1
