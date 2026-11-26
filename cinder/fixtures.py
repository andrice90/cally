"""Demo cards for developing the deck UI. Not used in production runs."""

from __future__ import annotations

from .db import DB


def _card(kind, title, pitch, why, effort, value, repo=None, **extra):
    base = {
        "kind": kind,
        "title": title,
        "pitch": pitch,
        "why": why,
        "effort": effort,
        "summary": extra.get("summary", pitch + " This is a demo card used while building the deck UI."),
        "why_now": extra.get("why_now", "Demo content: timing notes would go here."),
        "seo": extra.get("seo", "Demo content: target keywords and search intent would go here."),
        "agent_visibility": extra.get(
            "agent_visibility", "Demo content: llms.txt, an MCP server, and agent-readable docs."
        ),
        "competitors": extra.get("competitors", ["Example Co (a demo competitor)"]),
        "evidence": extra.get("evidence", [{"claim": "Example claim (demo)", "url": "https://example.com/"}]),
        "fit": extra.get("fit", "Builds on the demo repos."),
        "value": value,
    }
    if repo:
        base["repo"] = repo
    return base


DEMO_CARDS = [
    _card("feature", "Weekly digest email for saved items",
          "Send users a Monday summary of everything they saved but haven't opened.",
          ["Re-engagement emails lift weekly actives", "Digest formats are trending in newsletters",
           "Reuses the existing saved-items table"], "S", 88, repo="demo/reading-list"),
    _card("project", "Changelog-as-a-service for indie apps",
          "A hosted, SEO-friendly changelog page generated from your merged PRs.",
          ["Indie devs pay for small hosted tools", "Release notes are increasingly read by AI agents",
           "Fits your GitHub automation work"], "M", 81),
    _card("feature", "MCP server for the recipe API",
          "Expose search and meal plans as MCP tools so assistants can recommend recipes.",
          ["Agent-readable APIs get cited more", "MCP adoption is growing fast",
           "The API already has clean JSON endpoints"], "S", 77, repo="demo/recipes-api"),
    _card("feature", "Offline mode for the habit tracker",
          "Queue check-ins while offline and sync when the connection returns.",
          ["Top complaint in similar apps' reviews", "PWAs are getting better offline APIs",
           "The app is already a PWA"], "M", 64, repo="demo/habits"),
    _card("project", "llms.txt generator and linter",
          "Point it at a docs site; get a valid llms.txt plus a report of what agents can't read.",
          ["Site owners want to show up in AI answers", "llms.txt is spreading across docs sites",
           "Reuses your static-site tooling"], "S", 72),
    _card("feature", "Shareable public profile pages",
          "Let users publish a read-only page of their stats with Open Graph previews.",
          ["Shareable pages drive organic signups", "Social proof features are trending",
           "Stats are already computed server-side"], "L", 55, repo="demo/habits"),
]


def seed(db: DB) -> int:
    existing = {r["title"] for r in db.all("SELECT title FROM cards")}
    n = 0
    with db.tx() as c:
        for card in DEMO_CARDS:
            if card["title"] in existing:
                continue
            db.add_card(c, None, dict(card))
            n += 1
    return n
