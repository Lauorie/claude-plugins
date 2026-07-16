#!/usr/bin/env python3
"""Stop hook (Python entry): citation verification gate for the non-skill writing path.

Replaces the previous Node.js hook so the plugin runs in runtimes that ship
``python3`` but not ``node`` (e.g. the AutoReproBackend agent runtime, whose
container has no node on PATH → the old `node …citation-gate.js` exited 127).

解析 transcript 找本会话改过的 .tex/.bib/.md,有引用就跑 bundled ``citation_gate``
校验器(**进程内 import**,不再 subprocess/依赖 node);HARD_FAIL → block 返工
(最多 MAX_ROUNDS 轮防死锁),否则放行。全程 fail-open。

识别的写文件工具:原生 Write/Edit/MultiEdit **以及** universal-agent 的
``ChunkWrite`` MCP 工具(``mcp__*__ChunkWrite``)——后者是老 Write/Edit-only 收集
恒空的根因(与 #824 同源)。
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# The bundled ``citation_gate`` package lives at <PLUGIN_ROOT>/citation_gate.
PLUGIN_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT") or str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, PLUGIN_ROOT)

HOME = os.path.expanduser("~")
# Per-user block-round counters stay under the user's home, not the plugin.
ROUNDS_DIR = os.path.join(HOME, ".claude", ".cache", "citation_gate", "rounds")
MAX_ROUNDS = 3
EXTS = {".tex", ".bib", ".md"}

# Native write tools whose ``file_path`` input names a file the agent authored.
_NATIVE_WRITE = {"Write", "Edit", "MultiEdit"}

_CITATION_RE = re.compile(r"\\bibitem|\\cite|\[\d+\]|@(inproceedings|article|misc|book)\b")


def _is_write_tool(name: str) -> bool:
    """True for native Write/Edit/MultiEdit and any MCP-namespaced ChunkWrite
    (e.g. ``mcp__universal-agent-chunk-write__ChunkWrite``)."""
    if name in _NATIVE_WRITE:
        return True
    return name.split("__")[-1] == "ChunkWrite"


def _collect_candidate_files(transcript_path: str, cwd: str) -> list[str]:
    seen: list[str] = []
    try:
        lines = Path(transcript_path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        content = (ev.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            if not _is_write_tool(block.get("name") or ""):
                continue
            fp = (block.get("input") or {}).get("file_path")
            if not fp or not isinstance(fp, str):
                continue
            # ChunkWrite often gets a workspace-relative path; resolve against the
            # session cwd so the existence/extension checks below are correct.
            if not os.path.isabs(fp):
                fp = os.path.join(cwd or ".", fp)
            fp = os.path.normpath(fp)
            if (os.path.splitext(fp)[1].lower() in EXTS
                    and os.path.isfile(fp) and fp not in seen):
                seen.append(fp)
    return seen


def _has_citation_signal(fp: str) -> bool:
    try:
        text = Path(fp).read_text(encoding="utf-8")
    except OSError:
        return False
    if "<!-- citation-gate: skip -->" in text:
        return False
    return bool(_CITATION_RE.search(text))


def _rounds_file(session_id: str) -> str:
    return os.path.join(ROUNDS_DIR, f"{session_id}.json")


def _read_rounds(session_id: str) -> int:
    try:
        with open(_rounds_file(session_id), encoding="utf-8") as f:
            return int(json.load(f).get("n", 0))
    except (OSError, ValueError):
        return 0


def _bump_rounds(session_id: str) -> int:
    os.makedirs(ROUNDS_DIR, exist_ok=True)
    n = _read_rounds(session_id) + 1
    with open(_rounds_file(session_id), "w", encoding="utf-8") as f:
        json.dump({"n": n}, f)
    return n


def _reset_rounds(session_id: str) -> None:
    try:
        os.unlink(_rounds_file(session_id))
    except OSError:
        pass


def _run_verifier(files: list[str]) -> dict:
    """Import the bundled verifier in-process and return its report dict."""
    from citation_gate.verify import verify_files
    return verify_files(files).to_dict()


def _decide(report: dict, round_count: int, max_rounds: int) -> tuple[bool, str]:
    hard = report.get("hard_fail") or []
    soft = report.get("soft_warn") or []
    skip = report.get("skip") or []
    if not hard:
        msg = "引用校验通过。"
        if soft:
            msg += f" {len(soft)} 条未能核实,已标 [unverified],请人工确认。"
        if skip:
            msg += (f" 另有 {len(skip)} 条未核验(时间预算/网络限制),"
                    f"可调大 CITATION_GATE_BUDGET 或手动运行 python3 -m citation_gate 补检。")
        return False, msg
    detail = "\n".join(f"  [{h['index']}] {h['message']}" for h in hard)
    if round_count >= max_rounds:
        return False, (f"引用校验仍有 {len(hard)} 条疑似编造,但已达返工上限({max_rounds} 轮),放行。"
                       f"请人工(manual)复核:\n{detail}")
    return True, f"检测到 {len(hard)} 条疑似编造的引用,请逐条按权威记录修正后再交付:\n{detail}"


def _pass(sys_msg: str | None = None) -> None:
    print(json.dumps({"continue": True, "systemMessage": sys_msg} if sys_msg
                     else {"continue": True}, ensure_ascii=False))
    sys.exit(0)


def main() -> None:
    try:
        raw = sys.stdin.read()
        inp = json.loads(raw) if raw.strip() else {}
    except ValueError:
        inp = {}

    if os.environ.get("CITATION_GATE") == "off":
        _pass()
    session_id = inp.get("session_id") or "unknown"
    cwd = inp.get("cwd") or os.getcwd()

    files = [f for f in _collect_candidate_files(inp.get("transcript_path") or "", cwd)
             if _has_citation_signal(f)]
    if not files:
        _reset_rounds(session_id)
        _pass()

    try:
        report = _run_verifier(files)
    except Exception as e:  # fail-open: never break delivery on verifier error
        _pass(f"引用校验器未能运行({str(e)[:120]}),本次跳过。")

    round_count = _read_rounds(session_id)
    block, msg = _decide(report, round_count, MAX_ROUNDS)
    if block:
        _bump_rounds(session_id)
        print(json.dumps({"decision": "block", "reason": msg}, ensure_ascii=False))
        sys.exit(0)
    _reset_rounds(session_id)
    _pass(msg)


if __name__ == "__main__":
    main()
