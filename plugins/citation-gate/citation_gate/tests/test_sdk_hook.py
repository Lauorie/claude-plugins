"""SDK adapter for anthropics/claude-agent-sdk-python.

`make_stop_hook` returns a callback that duck-types the SDK's `HookCallback`:
  async (input_data, tool_use_id, context) -> HookJSONOutput   (a plain dict)
On a HARD_FAIL it returns {"decision": "block", "reason": ...} (the exact
SyncHookJSONOutput contract for blocking a Stop); otherwise {}. It must NOT
import claude_agent_sdk, so the verifier stays zero-dependency and the callback
works whether or not the SDK is installed."""
import asyncio
import inspect
from unittest.mock import patch

import pytest

from citation_gate.sdk_hook import make_stop_hook
from citation_gate.models import Citation, CitationResult, Verdict
from citation_gate.report import Report

CTX = {"signal": None}


def _hard_report():
    c = Citation(raw_text="[3] ...", index=3)
    return Report([CitationResult(c, Verdict.HARD_FAIL, None, ("authors",),
                                  "作者疑似编造")])


def _clean_report():
    c = Citation(raw_text="[1] ...", index=1)
    return Report([CitationResult(c, Verdict.PASS, None, (), "通过")])


def test_callback_matches_sdk_hookcallback_signature():
    hook = make_stop_hook(files=["/nope.md"])
    assert inspect.iscoroutinefunction(hook)
    assert len(inspect.signature(hook).parameters) == 3


def test_blocks_with_decision_block_on_hard_fail(tmp_path):
    f = tmp_path / "p.md"; f.write_text("[3] x", encoding="utf-8")
    hook = make_stop_hook(files=[str(f)])
    with patch("citation_gate.sdk_hook.verify_files", return_value=_hard_report()):
        out = asyncio.run(hook({"hook_event_name": "Stop"}, None, CTX))
    assert out.get("decision") == "block"
    assert "3" in out["reason"]
    assert "作者疑似编造" in out["reason"]


def test_returns_empty_dict_when_clean(tmp_path):
    f = tmp_path / "p.md"; f.write_text("[1] x", encoding="utf-8")
    hook = make_stop_hook(files=[str(f)])
    with patch("citation_gate.sdk_hook.verify_files", return_value=_clean_report()):
        out = asyncio.run(hook({}, None, CTX))
    assert out == {}


def test_fails_open_when_verifier_raises(tmp_path):
    f = tmp_path / "p.md"; f.write_text("[1] x", encoding="utf-8")
    hook = make_stop_hook(files=[str(f)])
    with patch("citation_gate.sdk_hook.verify_files", side_effect=RuntimeError("net")):
        out = asyncio.run(hook({}, None, CTX))
    assert out == {}  # never crash the agent on a verification error


def test_skips_verification_when_no_existing_files():
    hook = make_stop_hook(files=["/nonexistent/x.md"])
    with patch("citation_gate.sdk_hook.verify_files") as vf:
        out = asyncio.run(hook({}, None, CTX))
    vf.assert_not_called()
    assert out == {}


def test_files_provider_receives_input_data(tmp_path):
    f = tmp_path / "p.md"; f.write_text("x", encoding="utf-8")
    captured = {}

    def provider(input_data):
        captured.update(input_data)
        return [str(f)]

    hook = make_stop_hook(files=provider)
    with patch("citation_gate.sdk_hook.verify_files",
               return_value=_clean_report()) as vf:
        asyncio.run(hook({"cwd": "/work"}, None, CTX))
    assert captured.get("cwd") == "/work"
    vf.assert_called_once()


def test_registers_with_real_sdk_hookmatcher():
    """Integration: the callback is accepted by the real SDK's HookMatcher.
    Skipped unless anthropics/claude-agent-sdk-python is installed."""
    sdk = pytest.importorskip("claude_agent_sdk")
    hook = make_stop_hook(files=[])
    hm = sdk.HookMatcher(hooks=[hook])
    assert hook in hm.hooks
