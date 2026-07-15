"""Tests for the Python Stop-hook entry (hooks/citation-gate.py).

Focus on the two behaviours the Node hook lacked / that regressed in prod:
1. ChunkWrite (mcp__*__ChunkWrite) is recognized as a write tool — the old
   Write/Edit-only collection was inert for universal-agent output.
2. Candidate collection + citation-signal detection over a realistic transcript.

Run: python3 -m pytest hooks/tests/test_citation_gate_hook.py
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_HOOK = Path(__file__).resolve().parents[1] / "citation-gate.py"
_spec = importlib.util.spec_from_file_location("citation_gate_hook", _HOOK)
hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hook)


def test_is_write_tool_native_and_chunkwrite():
    assert hook._is_write_tool("Write")
    assert hook._is_write_tool("Edit")
    assert hook._is_write_tool("MultiEdit")
    # MCP-namespaced ChunkWrite (both the universal-agent and plain variants).
    assert hook._is_write_tool("mcp__universal-agent-chunk-write__ChunkWrite")
    assert hook._is_write_tool("mcp__chunk-write__ChunkWrite")
    # Not a write tool.
    assert not hook._is_write_tool("Bash")
    assert not hook._is_write_tool("mcp__wispaper-search__search_papers")


def _write_transcript(dir_path: Path, tool_name: str, file_path: str) -> Path:
    """One assistant event carrying a single tool_use block."""
    event = {"message": {"content": [
        {"type": "text", "text": "writing the review"},
        {"type": "tool_use", "name": tool_name,
         "input": {"file_path": file_path, "content": "x", "mode": "create"}},
    ]}}
    tp = dir_path / "transcript.jsonl"
    tp.write_text(json.dumps(event) + "\n", encoding="utf-8")
    return tp


def test_collect_recognizes_chunkwrite_file(tmp_path):
    md = tmp_path / "review.md"
    md.write_text("See [1].\n", encoding="utf-8")
    # ChunkWrite wrote a workspace-relative path; hook must resolve it against cwd.
    tp = _write_transcript(tmp_path, "mcp__universal-agent-chunk-write__ChunkWrite", "review.md")
    found = hook._collect_candidate_files(str(tp), cwd=str(tmp_path))
    assert found == [str(md)]


def test_collect_ignores_non_target_extension(tmp_path):
    py = tmp_path / "script.py"
    py.write_text("print(1)\n", encoding="utf-8")
    tp = _write_transcript(tmp_path, "mcp__universal-agent-chunk-write__ChunkWrite", "script.py")
    assert hook._collect_candidate_files(str(tp), cwd=str(tmp_path)) == []


def test_collect_native_write_absolute_path(tmp_path):
    tex = tmp_path / "paper.tex"
    tex.write_text("\\cite{foo}\n", encoding="utf-8")
    tp = _write_transcript(tmp_path, "Write", str(tex))  # absolute path
    assert hook._collect_candidate_files(str(tp), cwd="/nonexistent") == [str(tex)]


def test_has_citation_signal(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("Related work [1] and [2].\n", encoding="utf-8")
    assert hook._has_citation_signal(str(f))
    f.write_text("@article{x, title={t}}\n", encoding="utf-8")
    assert hook._has_citation_signal(str(f))
    f.write_text("No citations here.\n", encoding="utf-8")
    assert not hook._has_citation_signal(str(f))
    # Opt-out marker suppresses the gate.
    f.write_text("[1] real ref\n<!-- citation-gate: skip -->\n", encoding="utf-8")
    assert not hook._has_citation_signal(str(f))


def test_decide_blocks_on_hard_fail():
    report = {"hard_fail": [{"index": 1, "message": "fabricated DOI"}], "soft_warn": []}
    block, msg = hook._decide(report, round_count=0, max_rounds=3)
    assert block is True
    assert "疑似编造" in msg and "[1]" in msg


def test_decide_passes_after_max_rounds():
    report = {"hard_fail": [{"index": 1, "message": "fabricated DOI"}], "soft_warn": []}
    block, msg = hook._decide(report, round_count=3, max_rounds=3)
    assert block is False
    assert "返工上限" in msg


def test_decide_passes_clean():
    block, msg = hook._decide({"hard_fail": [], "soft_warn": []}, round_count=0, max_rounds=3)
    assert block is False
    assert "通过" in msg
