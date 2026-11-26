import asyncio
import json
from datetime import UTC, datetime

import pytest

from cinder import agent
from cinder.db import DB, DEFAULT_SETTINGS, slugify
from cinder.runner import compute_slots
from cinder.scheduler import generation_time, run_due
from tests.conftest import FAKE_CLAUDE

S = dict(DEFAULT_SETTINGS)


def pend(f, p):
    return [{"kind": "feature"}] * f + [{"kind": "project"}] * p


@pytest.mark.parametrize("f,p,expect", [
    (0, 0, (7, 3)),
    (7, 3, (0, 0)),
    (5, 1, (2, 2)),
    (8, 0, (0, 2)),
    (0, 9, (1, 0)),
    (2, 3, (5, 0)),
    (10, 4, (0, 0)),
])
def test_compute_slots(f, p, expect):
    assert compute_slots(S, pend(f, p)) == expect


def test_slots_mix_not_summing_to_size():
    s = {**S, "deck_size": 12, "mix_features": 7, "mix_projects": 3}
    f, p = compute_slots(s, [])
    assert f + p == 12 and f >= 7 and p >= 3


def test_slugify():
    assert slugify("Weekly digest: email!") == "weekly-digest-email"
    assert slugify("!!!") == "idea"


def test_generation_time_follows_dst():
    winter = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    summer = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    assert generation_time("America/Chicago", "07:00", 120, winter).astimezone(UTC).hour == 11
    assert generation_time("America/Chicago", "07:00", 120, summer).astimezone(UTC).hour == 10


def test_run_due(tmp_path):
    db = DB(tmp_path / "x.db")
    early = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)  # 4 am CST
    later = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)  # 6 am CST
    assert not run_due(db, S, now=early)              # catch-up waits for 5 am
    assert run_due(db, S, wake=True, now=early)       # the scheduled wake doesn't
    assert run_due(db, S, now=later)
    db.run("INSERT INTO runs(kind,status,started_at,finished_at,local_date) VALUES('daily','failed',?,?,?)",
           (later.isoformat(), later.isoformat(), "2026-01-15"))
    assert not run_due(db, S, now=later)              # just failed: back off
    assert run_due(db, S, wake=True, now=later)
    db.run("INSERT INTO runs(kind,status,started_at,local_date) VALUES('daily','succeeded',?,?)",
           (later.isoformat(), "2026-01-15"))
    assert not run_due(db, S, wake=True, now=later)
    tomorrow = datetime(2026, 1, 16, 12, 0, tzinfo=UTC)
    assert run_due(db, S, now=tomorrow)


async def test_agent_flags_and_output(tmp_path, monkeypatch):
    log = tmp_path / "log"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    monkeypatch.setenv("CINDER_SECRET_THING", "x")
    res = await agent.run_claude(str(FAKE_CLAUDE), "hello", agent.NEVER_RULE_SCHEMA, tools="",
                                 budget=0.2, timeout=20, cwd=tmp_path / "w")
    assert res.data["rule"] and res.cost == 0.01
    call = json.loads(log.read_text().splitlines()[0])
    argv = call["argv"]
    for flag in ("-p", "--strict-mcp-config", "--no-session-persistence", "--permission-prompts"):
        assert flag in argv
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--setting-sources") + 1] == "project"
    assert argv[argv.index("--max-budget-usd") + 1] == "0.20"
    assert "--bare" not in argv
    assert argv[argv.index("--allowedTools") + 1] == ""

    assert json.loads((tmp_path / "w" / ".empty-mcp.json").read_text()) == {"mcpServers": {}}
    assert call["cwd"] == str(tmp_path / "w")
    assert call["prompt"] == "hello"
    assert not call["env_has_secrets"]


@pytest.mark.parametrize("mode,msg", [("garbage", "non-JSON"), ("error", "error_max_budget_usd")])
async def test_agent_errors(tmp_path, monkeypatch, mode, msg):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
    with pytest.raises(agent.AgentError, match=msg):
        await agent.run_claude(str(FAKE_CLAUDE), "x", agent.NEVER_RULE_SCHEMA, tools="", budget=1,
                               timeout=20, cwd=tmp_path)


async def test_agent_timeout_kills(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "sleep")
    t0 = asyncio.get_running_loop().time()
    with pytest.raises(agent.AgentError, match="timed out"):
        await agent.run_claude(str(FAKE_CLAUDE), "x", agent.NEVER_RULE_SCHEMA, tools="", budget=1,
                               timeout=1, cwd=tmp_path)
    assert asyncio.get_running_loop().time() - t0 < 5


async def test_agent_schema_validation(tmp_path):
    # The fake returns {"rule": ...}; a schema demanding something else must be rejected.
    schema = {"type": "object", "required": ["rule", "other"], "properties": {"rule": {"type": "string"}}}
    with pytest.raises(agent.AgentError, match="schema"):
        await agent.run_claude(str(FAKE_CLAUDE), "x", schema, tools="", budget=1, timeout=20, cwd=tmp_path)


def test_allowed_tools_scopes_reads_to_work_dir():
    assert agent.allowed_tools(agent.WEB_TOOLS) == "WebSearch,WebFetch,Read(./**)"
    assert agent.allowed_tools(agent.READ_TOOLS) == "Read(./**)"
    assert agent.allowed_tools("") == ""
    assert "Read," not in agent.allowed_tools(agent.WEB_TOOLS) + ","
