"""_decide must surface unverified (SKIP) counts in the pass message —
citations the verifier never reached must not read as fully verified."""
import importlib.util
from pathlib import Path

_HOOK_PATH = Path(__file__).resolve().parent.parent / "citation-gate.py"
_spec = importlib.util.spec_from_file_location("citation_gate_hook", _HOOK_PATH)
hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hook)


def test_pass_message_surfaces_skip_count():
    report = {"hard_fail": [], "soft_warn": [],
              "skip": [{"index": i, "message": "时间预算耗尽"} for i in range(4)]}
    block, msg = hook._decide(report, 0, 3)
    assert block is False
    assert "4" in msg and "未核验" in msg


def test_plain_pass_message_unchanged():
    block, msg = hook._decide({"hard_fail": [], "soft_warn": [], "skip": []}, 0, 3)
    assert block is False
    assert msg == "引用校验通过。"
