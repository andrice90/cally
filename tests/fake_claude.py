#!/usr/bin/env python3
"""Stand-in for the `claude` CLI in tests. Behaviour is chosen from the --json-schema and FAKE_CLAUDE_* env."""

import json
import os
import re
import sys
import time
from pathlib import Path


def arg(name):
    a = sys.argv
    return a[a.index(name) + 1] if name in a else None


prompt = sys.stdin.read()
schema = json.loads(arg("--json-schema") or "{}")
log = os.environ.get("FAKE_CLAUDE_LOG")
if log:
    with open(log, "a") as fh:
        fh.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd(), "prompt": prompt,
                             "env_has_secrets": any(k.startswith(("CINDER_", "GITHUB_")) for k in os.environ)}) + "\n")

mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
if mode == "sleep":
    time.sleep(30)
if mode == "garbage":
    print("not json")
    sys.exit(1)
if mode == "error":
    print(json.dumps({"type": "result", "is_error": True, "subtype": "error_max_budget_usd", "total_cost_usd": 0.5}))
    sys.exit(1)

props = schema.get("properties", {})
if "cards" in props:
    nf = int(re.search(r"\*\*(\d+) feature card", prompt).group(1))
    np_ = int(re.search(r"\*\*(\d+) new-project card", prompt).group(1))
    repos = []
    for f in sorted(Path("repos").glob("*.md")):
        first = f.read_text().splitlines()[0]
        repos.append(first.removeprefix("# ").strip())
    seen = Path("seen.md").read_text()
    run = len(seen.splitlines())
    cards = []
    bad = mode == "badcards"
    for i in range(nf + (1 if bad else 0)):
        repo = repos[i % len(repos)] if not (bad and i == nf) else "someone/unknown"
        cards.append({"kind": "feature", "repo": repo, "title": f"Feature idea {run}-{i}", "pitch": "Do a thing.",
                      "why": ["market", "trend", "fit"], "effort": "S", "summary": "s", "why_now": "w",
                      "seo": "k", "agent_visibility": "a", "competitors": ["c"],
                      "evidence": [{"claim": "x", "url": "https://example.com/x"}, {"claim": "bad", "url": "javascript:alert(1)"}],
                      "fit": "f", "value": 50 + i})
    for i in range(np_):
        cards.append({"kind": "project", "title": f"Project idea {run}-{i}", "pitch": "Build a thing.",
                      "why": ["market", "trend", "fit"], "effort": "M", "summary": "s", "why_now": "w",
                      "seo": "k", "agent_visibility": "a", "competitors": [], "evidence": [], "fit": "f",
                      "value": 90 - i})
    if mode == "dupes" and cards:
        cards.append(dict(cards[0]))
    out = {"cards": cards}
elif "rule" in props:
    out = {"rule": "No more ideas about things like that"}
elif "markdown" in props:
    if "preference profile" in prompt:
        out = {"markdown": "## Liked themes\n- learned from " + str(prompt.count("\n- ")) + " swipes"}
    else:
        out = {"markdown": "# Spec\n\n## Problem & opportunity\nA spec body."}
else:
    out = {}

print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.01,
                  "result": json.dumps(out), "structured_output": out}))
