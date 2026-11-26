"""Wrapper around the `claude` CLI in print mode (spec §9), plus prompts and output schemas."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from dataclasses import dataclass
from pathlib import Path
from string import Template

import jsonschema

log = logging.getLogger("cally.agent")
PROMPTS = Path(__file__).parent / "prompts"

WEB_TOOLS = "WebSearch,WebFetch,Read,Glob,Grep"
READ_TOOLS = "Read,Glob,Grep"

CARD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "kind", "title", "pitch", "why", "effort", "summary", "why_now", "seo",
        "agent_visibility", "competitors", "evidence", "fit", "value",
    ],
    "properties": {
        "kind": {"type": "string", "enum": ["feature", "project"]},
        "repo": {"type": "string", "description": "owner/name; required for features"},
        "title": {"type": "string", "maxLength": 70},
        "pitch": {"type": "string", "maxLength": 200},
        "why": {"type": "array", "items": {"type": "string", "maxLength": 140}, "minItems": 3, "maxItems": 3},
        "effort": {"type": "string", "enum": ["S", "M", "L"]},
        "summary": {"type": "string"},
        "why_now": {"type": "string"},
        "seo": {"type": "string"},
        "agent_visibility": {"type": "string"},
        "competitors": {"type": "array", "items": {"type": "string"}},
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["claim", "url"],
                "properties": {"claim": {"type": "string"}, "url": {"type": "string"}},
            },
        },
        "fit": {"type": "string"},
        "value": {"type": "integer", "minimum": 0, "maximum": 100},
    },
}
IDEATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["cards"],
    "properties": {"cards": {"type": "array", "items": CARD_SCHEMA}},
}
PROFILE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["markdown"],
    "properties": {"markdown": {"type": "string"}},
}
SPEC_SCHEMA = PROFILE_SCHEMA
NEVER_RULE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["rule"],
    "properties": {"rule": {"type": "string", "maxLength": 200}},
}


class AgentError(RuntimeError):
    def __init__(self, message: str, cost: float = 0.0):
        super().__init__(message)
        self.cost = cost


@dataclass
class AgentResult:
    data: dict
    cost: float


def render(name: str, **values) -> str:
    return Template((PROMPTS / f"{name}.md").read_text()).safe_substitute(**values)


def allowed_tools(tools: str) -> str:
    """Pre-approve tools, scoping file reads to the work dir.

    A bare "Read" would approve reads of any path (e.g. ~/.cally/env). "Read(./**)" approves only the
    work dir; anything else would need a permission prompt, which --permission-prompts none denies.
    Glob and Grep inside the work dir need no approval, so they aren't listed.
    """
    out = []
    for t in (t.strip() for t in tools.split(",")):
        if not t or t in ("Glob", "Grep"):
            continue
        out.append("Read(./**)" if t == "Read" else t)
    return ",".join(out)


def _child_env() -> dict[str, str]:
    """The agent never sees Cally's secrets."""
    drop = ("CALLY_", "GITHUB_", "AGENTMAIL")
    return {k: v for k, v in os.environ.items() if not k.startswith(drop)}


async def run_claude(
    claude_bin: str,
    prompt: str,
    schema: dict,
    *,
    tools: str,
    budget: float,
    timeout: float,
    cwd: Path,
) -> AgentResult:
    cwd.mkdir(parents=True, exist_ok=True)
    mcp = cwd / ".empty-mcp.json"
    mcp.write_text('{"mcpServers":{}}')
    args = [
        "-p",
        "--output-format", "json",
        "--json-schema", json.dumps(schema),
        "--tools", tools,
        "--allowedTools", allowed_tools(tools),
        "--permission-prompts", "none",
        "--strict-mcp-config", "--mcp-config", str(mcp),
        "--setting-sources", "project",
        "--no-session-persistence",
        "--max-budget-usd", f"{budget:.2f}",
    ]
    proc = await asyncio.create_subprocess_exec(
        claude_bin,
        *args,
        cwd=str(cwd),
        env=_child_env(),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(prompt.encode()), timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise AgentError(f"agent timed out after {int(timeout)}s")

    try:
        res = json.loads(out.decode() or "{}")
    except json.JSONDecodeError:
        log.warning("claude stderr: %s", err.decode()[-2000:])
        raise AgentError(f"agent returned non-JSON output (exit {proc.returncode})")
    cost = float(res.get("total_cost_usd") or 0)
    if res.get("is_error") or proc.returncode != 0:
        detail = res.get("subtype") or res.get("result") or f"exit {proc.returncode}"
        raise AgentError(f"agent failed: {str(detail)[:300]}", cost)
    data = res.get("structured_output")
    if data is None:
        try:
            data = json.loads(res.get("result") or "")
        except (json.JSONDecodeError, TypeError):
            raise AgentError("agent returned no structured output", cost)
    try:
        jsonschema.validate(data, schema)
    except jsonschema.ValidationError as exc:
        raise AgentError(f"agent output failed schema validation: {exc.message[:300]}", cost)
    return AgentResult(data=data, cost=cost)
