"""Stop-hook adapter for anthropics/claude-agent-sdk-python.

Register the returned callback with the SDK so a session cannot end while a
citation's bibliographic metadata is fabricated:

    from claude_agent_sdk import ClaudeAgentOptions, HookMatcher
    from citation_gate.sdk_hook import make_stop_hook

    options = ClaudeAgentOptions(
        hooks={"Stop": [HookMatcher(hooks=[make_stop_hook(files=["paper.md"])])]}
    )

The callback duck-types the SDK's HookCallback —
`async (input_data, tool_use_id, context) -> HookJSONOutput` (a plain dict) —
WITHOUT importing claude_agent_sdk, so this module stays zero-dependency and the
callback works whether or not the SDK is installed. On a HARD_FAIL it returns the
SDK's documented block contract ``{"decision": "block", "reason": ...}``;
otherwise ``{}``. It never raises (fail-open): a verification or network error
must not break the agent loop.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Union

from .cache import Cache
from .report import Report
from .verify import verify_files

logger = logging.getLogger(__name__)

_CITATION_SUFFIXES = (".md", ".tex", ".bib")
# Either a fixed list of paths, or a callable given the hook input_data dict.
FilesArg = Union[Sequence[str], Callable[[Dict[str, Any]], Sequence[str]]]


def _resolve_files(files: FilesArg, input_data: Dict[str, Any]) -> List[str]:
    raw = files(input_data) if callable(files) else files
    return [p for p in (raw or ())
            if p and os.path.isfile(p) and p.lower().endswith(_CITATION_SUFFIXES)]


def _format_block_reason(report: Report) -> str:
    lines = ["引用元数据校验未通过（citation-gate），疑似编造的参考文献字段："]
    lines += [f"- [{r.citation.index}] {r.message}" for r in report.hard_fails]
    lines.append("请用权威检索（DBLP / Semantic Scholar / CrossRef）核对后修正，再结束。")
    return "\n".join(lines)


def make_stop_hook(
    files: FilesArg, *, cache: Optional[Cache] = None
) -> Callable[[Dict[str, Any], Optional[str], Any], Awaitable[Dict[str, Any]]]:
    """Build a Stop-hook callback for the Claude Agent SDK.

    Args:
        files: citation files to verify, or a callable receiving the hook
            `input_data` dict and returning such a list (e.g. to compute paths
            from the session cwd at stop time).
        cache: optional shared verification cache.

    Returns:
        An async callback with the SDK HookCallback signature
        `(input_data, tool_use_id, context)` that returns a HookJSONOutput dict.
    """
    async def _stop_hook(input_data: Dict[str, Any], tool_use_id: Optional[str],
                         context: Any) -> Dict[str, Any]:
        try:
            paths = _resolve_files(files, input_data or {})
            if not paths:
                return {}
            # verify_files does blocking network I/O → keep the event loop free.
            report = await asyncio.to_thread(verify_files, paths, cache=cache)
            if not report.hard_fails:
                return {}
            return {"decision": "block", "reason": _format_block_reason(report)}
        except Exception as e:  # fail open: a checker error must not break the agent
            logger.warning("citation-gate SDK stop hook error (fail-open): %s", e)
            return {}

    return _stop_hook


__all__ = ["make_stop_hook"]
