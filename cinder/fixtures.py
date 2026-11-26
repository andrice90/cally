"""Generic demo content for demo mode (its own database; never mixed with real data)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .db import DB

DEMO_REPOS = [
    ("demo/reading-list", "Save articles and read them later", 2),
    ("demo/recipes-api", "A small REST API for recipes and meal plans", 3),
    ("demo/habit-tracker", "Track daily habits and streaks", 5),
    ("demo/portfolio-site", "Personal site and blog", 8),
    ("demo/budget-app", "Household budgeting with shared categories", 12),
    ("demo/cli-toolkit", "Command-line helpers for everyday dev tasks", 20),
    ("demo/photo-gallery", "Self-hosted photo albums", 45),
    ("demo/old-prototype", "An early experiment", 400),
]


def _card(kind, title, pitch, why, effort, value, repo=None, competitors=None, fit=None):
    card = {
        "kind": kind,
        "title": title,
        "pitch": pitch,
        "why": why,
        "effort": effort,
        "summary": pitch + " This is sample content for demo mode.",
        "why_now": "Sample timing notes: what changed recently that makes this worth doing now.",
        "seo": "Sample search angle: the keywords and questions people use when looking for this.",
        "agent_visibility": "Sample plan for being found by AI assistants: docs, llms.txt and an MCP server.",
        "competitors": competitors or ["Example Co: a sample competitor"],
        "evidence": [{"claim": "Sample source", "url": "https://example.com/"}],
        "fit": fit or "Builds on the sample repos.",
        "value": value,
    }
    if repo:
        card["repo"] = repo
    return card


DEMO_DECK = [
    _card("feature", "Weekly digest email for saved items",
          "Send a Monday summary of everything saved but not yet read.",
          ["Re-engagement emails lift weekly actives", "Digest formats are popular again",
           "Reuses the existing saved-items table"], "S", 92, repo="demo/reading-list"),
    _card("project", "Changelog pages for small apps",
          "A hosted, search-friendly changelog generated from merged pull requests.",
          ["Small teams pay for simple hosted tools", "Release notes are read by people and agents",
           "Fits your existing automation work"], "M", 88),
    _card("feature", "MCP server for the recipes API",
          "Expose recipe search and meal plans as tools that AI assistants can call.",
          ["Agent-readable APIs get recommended more", "Assistant tool use is growing quickly",
           "The API already returns clean JSON"], "S", 85, repo="demo/recipes-api"),
    _card("feature", "Offline check-ins for the habit tracker",
          "Queue check-ins without a connection and sync them when it returns.",
          ["A common request in reviews of similar apps", "Browsers now handle offline storage well",
           "The app is already installable"], "M", 79, repo="demo/habit-tracker"),
    _card("project", "llms.txt generator and checker",
          "Point it at a docs site to get a valid llms.txt and a list of pages agents can't read.",
          ["Site owners want to appear in AI answers", "llms.txt adoption keeps spreading",
           "Reuses your static-site tooling"], "S", 76),
    _card("feature", "Shared categories with spending limits",
          "Let two people share budget categories and get a nudge near the limit.",
          ["Couples budgeting is an underserved niche", "Shared finance features are trending",
           "Categories already exist in the data model"], "M", 71, repo="demo/budget-app"),
    _card("feature", "Reading time and series for blog posts",
          "Show reading time and group related posts into series with next/previous links.",
          ["Series keep readers on site longer", "Long-form tutorials are doing well in search",
           "Posts already have tags to group by"], "S", 66, repo="demo/portfolio-site"),
    _card("feature", "Config profiles for the CLI",
          "Switch between named profiles for different projects with one flag.",
          ["A top request for similar tools", "Multi-project setups are now the norm",
           "Settings are already loaded from one file"], "S", 61, repo="demo/cli-toolkit"),
    _card("project", "Tiny status page for side projects",
          "A free, minimal status page that checks your sites and posts incidents.",
          ["Indie makers want trust signals cheaply", "Uptime tools have moved upmarket",
           "Reuses your hosting and alerting know-how"], "M", 58),
    _card("feature", "Shareable albums with expiring links",
          "Share an album with a link that stops working after a set date.",
          ["Privacy-conscious sharing is in demand", "Expiring links are now expected",
           "Albums and auth already exist"], "M", 52, repo="demo/photo-gallery"),
]

DEMO_HISTORY = [
    # (card, status, note, never, spec status)
    (_card("feature", "Dark mode for the reader view", "Add a dark theme that follows the system setting.",
           ["Frequently requested", "Expected by default now", "Styles already use variables"], "S", 70,
           repo="demo/reading-list"), "liked", "Keep it to the reader view first", False, "pr_open"),
    (_card("project", "Enterprise sales CRM", "A CRM for agencies with pipelines and invoicing.",
           ["Large market", "Agencies switch tools often", "Some overlap with past work"], "L", 40),
     "dismissed", "Not interested in sales-heavy products", False, None),
    (_card("feature", "Crypto rewards for streaks", "Turn habit streaks into collectible tokens.",
           ["Gamification boosts retention", "Web3 loyalty experiments", "Streaks already tracked"], "M", 30,
           repo="demo/habit-tracker"), "dismissed", None, True, None),
]

DEMO_PROFILE = """## Liked themes
- Small, practical features that build on code that already exists
- Tools that make projects easier for AI assistants to find and use

## Disliked themes
- Sales-heavy B2B products
- Crypto and token-based rewards

## Effort preferences
- Prefers small (S) and medium (M) ideas

## Notes in their own words
- "Keep it to the reader view first"
- "Not interested in sales-heavy products"
"""


def reset_demo(db: DB) -> None:
    """Replace everything in the demo database with fresh generic content."""
    now = datetime.now(UTC)
    ts = lambda d=timedelta(0): (now - d).isoformat(timespec="microseconds")  # noqa: E731
    with db.tx() as c:
        for table in ("specs", "never_rules", "cards", "runs", "profile", "repos"):
            c.execute(f"DELETE FROM {table}")
        for i, (name, desc, days) in enumerate(DEMO_REPOS, start=1):
            c.execute(
                "INSERT INTO repos(id, full_name, description, default_branch, pushed_at, archived, fork, "
                "private, excluded, digest) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (i, name, desc, "main", ts(timedelta(days=days)), int(days > 300), 0, int(i % 3 == 0),
                 int(days > 300), f"# {name}\n{desc}"),
            )
        c.execute(
            "INSERT INTO runs(kind, status, step, started_at, finished_at, cost_usd, new_cards, local_date) "
            "VALUES('daily','succeeded','done',?,?,0,?,?)",
            (ts(timedelta(hours=3)), ts(timedelta(hours=3) - timedelta(minutes=5)), len(DEMO_DECK),
             now.date().isoformat()),
        )
        for card in DEMO_DECK:
            db.add_card(c, None, dict(card))
        for n, (card, status, note, never, spec) in enumerate(DEMO_HISTORY):
            cid = db.add_card(c, None, dict(card))
            c.execute(
                "UPDATE cards SET status=?, note=?, never=?, decided_at=? WHERE id=?",
                (status, note, int(never), ts(timedelta(days=n + 1)), cid),
            )
            if spec:
                c.execute(
                    "INSERT INTO specs(card_id, status, created_at, updated_at) VALUES(?,?,?,?)",
                    (cid, spec, ts(timedelta(days=n + 1)), ts(timedelta(days=n + 1))),
                )
            if never:
                c.execute(
                    "INSERT INTO never_rules(text, card_id, created_at) VALUES(?,?,?)",
                    ("Avoid crypto, token or blockchain reward features", cid, ts(timedelta(days=n + 1))),
                )
        c.execute(
            "INSERT INTO profile(id, markdown, updated_at, swipes_through) VALUES(1,?,?,?)",
            (DEMO_PROFILE, ts(timedelta(hours=3)), ts(timedelta(hours=3))),
        )

