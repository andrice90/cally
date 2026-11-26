"""The daily summary email: what's waiting today, yesterday's new specs, and yesterday's activity."""

from __future__ import annotations

import html
import json
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .db import DB

EFFORT = {"S": "small", "M": "medium", "L": "large"}


def _day_bounds(tz: str, now: datetime | None = None) -> tuple[str, str, str]:
    """UTC ISO bounds for yesterday's start, today's start, and tomorrow's start in the given zone."""
    zone = ZoneInfo(tz)
    today = (now or datetime.now(UTC)).astimezone(zone).date()
    start = lambda d: datetime.combine(d, time.min, zone).astimezone(UTC).isoformat()  # noqa: E731
    return start(today - timedelta(days=1)), start(today), start(today + timedelta(days=1))


def gather(db: DB, base_url: str, now: datetime | None = None) -> dict:
    s = db.settings()
    y0, t0, _ = _day_bounds(s["tz"], now)
    deck = db.all("SELECT * FROM cards WHERE status='pending' ORDER BY value DESC, id")
    waiting = []
    for c in deck:
        p = json.loads(c["payload_json"])
        waiting.append({
            "title": c["title"], "kind": c["kind"], "repo": c["repo"], "effort": p.get("effort", ""),
            "pitch": p.get("pitch", ""), "new": c["created_at"] >= t0,
        })
    opened = db.all(
        "SELECT c.title, c.kind, c.repo, s.pr_url FROM specs s JOIN cards c ON c.id = s.card_id "
        "WHERE s.status='pr_open' AND s.updated_at >= ? AND s.updated_at < ? ORDER BY s.updated_at",
        (y0, t0),
    )
    failed = db.all(
        "SELECT c.title, s.error FROM specs s JOIN cards c ON c.id = s.card_id "
        "WHERE s.status='failed' AND s.updated_at >= ? AND s.updated_at < ?",
        (y0, t0),
    )
    swipes = db.one(
        "SELECT SUM(status='liked') AS saved, SUM(status='dismissed') AS dismissed, SUM(never) AS never, "
        "SUM(note IS NOT NULL AND note != '') AS notes FROM cards WHERE decided_at >= ? AND decided_at < ?",
        (y0, t0),
    ) or {}
    runs = db.one(
        "SELECT COUNT(*) AS n, COALESCE(SUM(cost_usd), 0) AS cost FROM runs WHERE started_at >= ? AND started_at < ?",
        (y0, t0),
    ) or {}
    today_run = db.one("SELECT status, error, new_cards, cost_usd FROM runs WHERE started_at >= ? ORDER BY id DESC LIMIT 1", (t0,))
    return {
        "waiting": waiting,
        "new_today": sum(1 for w in waiting if w["new"]),
        "opened": opened,
        "failed": failed,
        "saved": int(swipes.get("saved") or 0),
        "dismissed": int(swipes.get("dismissed") or 0),
        "never": int(swipes.get("never") or 0),
        "notes": int(swipes.get("notes") or 0),
        "runs": int(runs.get("n") or 0),
        "cost": float(runs.get("cost") or 0),
        "today_run": today_run,
        "url": base_url.rstrip("/") + "/",
    }


def _where(w: dict) -> str:
    return w["repo"] if w["kind"] == "feature" and w["repo"] else "New project"


def subject(d: dict) -> str:
    n = len(d["waiting"])
    parts = [f"{n} idea{'s' if n != 1 else ''} waiting"]
    if d["opened"]:
        k = len(d["opened"])
        parts.append(f"{k} new spec{'s' if k != 1 else ''}")
    return "Cinder: " + ", ".join(parts)


def _activity_line(d: dict) -> str:
    if not (d["saved"] or d["dismissed"]):
        return "No swipes yesterday."
    line = f"Saved {d['saved']}, dismissed {d['dismissed']}"
    if d["never"]:
        line += f" ({d['never']} marked never)"
    if d["notes"]:
        line += f", {d['notes']} note{'s' if d['notes'] != 1 else ''}"
    return line + "."


def _run_line(d: dict) -> str | None:
    r = d["today_run"]
    if r and r["status"] == "failed":
        return f"This morning's run failed. {r['error'] or ''}".strip()
    return None


def render_text(d: dict) -> str:
    out = []
    problem = _run_line(d)
    if problem:
        out += [problem, ""]
    head = f"Waiting today ({len(d['waiting'])}"
    out.append(head + (f", {d['new_today']} new)" if d["new_today"] else ")"))
    if d["waiting"]:
        for w in d["waiting"]:
            effort = EFFORT.get(w["effort"], w["effort"])
            out.append(f"- {w['title']} ({_where(w)}, {effort})" + (" [new]" if w["new"] else ""))
    else:
        out.append("Nothing waiting.")
    out += ["", "New specs yesterday"]
    if d["opened"]:
        out += [f"- {o['title']}: {o['pr_url']}" for o in d["opened"]]
    else:
        out.append("None.")
    if d["failed"]:
        out += [f"- Failed: {f['title']}" for f in d["failed"]]
    out += ["", "Yesterday", _activity_line(d)]
    if d["runs"]:
        out.append(f"{d['runs']} run{'s' if d['runs'] != 1 else ''}, ${d['cost']:.2f}.")
    out += ["", f"Open your deck: {d['url']}"]
    return "\n".join(out) + "\n"


def _safe_url(u: str | None) -> str | None:
    return u if u and u.startswith(("https://", "http://")) else None


def render_html(d: dict) -> str:
    e = html.escape
    ink, faint, ember = "#2a211b", "#9a8a7d", "#d9481a"
    h2 = f'style="font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:{ember};margin:28px 0 8px"'
    li = 'style="margin:0 0 10px"'
    parts = [f'<div style="font-family:Georgia,\'Iowan Old Style\',serif;color:{ink};max-width:560px;font-size:16px;line-height:1.5">']
    problem = _run_line(d)
    if problem:
        parts.append(f'<p style="color:#b8322a">{e(problem)}</p>')
    count = f"{len(d['waiting'])}" + (f", {d['new_today']} new" if d["new_today"] else "")
    parts.append(f"<h2 {h2}>Waiting today ({e(count)})</h2>")
    if d["waiting"]:
        parts.append('<ul style="padding-left:18px;margin:0">')
        for w in d["waiting"]:
            meta = f"{_where(w)}, {EFFORT.get(w['effort'], w['effort'])}" + (", new" if w["new"] else "")
            parts.append(
                f'<li {li}><b>{e(w["title"])}</b><br><span style="color:{faint};font-style:italic">{e(meta)}</span></li>'
            )
        parts.append("</ul>")
    else:
        parts.append("<p>Nothing waiting.</p>")
    parts.append(f"<h2 {h2}>New specs yesterday</h2>")
    if d["opened"] or d["failed"]:
        parts.append('<ul style="padding-left:18px;margin:0">')
        for o in d["opened"]:
            url = _safe_url(o["pr_url"])
            link = f' <a href="{e(url)}" style="color:{ember}">View PR</a>' if url else ""
            parts.append(f"<li {li}>{e(o['title'])}{link}</li>")
        for f in d["failed"]:
            parts.append(f"<li {li}>{e(f['title'])} <span style=\"color:#b8322a\">failed</span></li>")
        parts.append("</ul>")
    else:
        parts.append("<p>None.</p>")
    parts.append(f"<h2 {h2}>Yesterday</h2><p style=\"margin:0\">{e(_activity_line(d))}</p>")
    if d["runs"]:
        parts.append(f'<p style="margin:4px 0 0">{d["runs"]} run{"s" if d["runs"] != 1 else ""}, ${d["cost"]:.2f}.</p>')
    parts.append(
        f'<p style="margin:32px 0 0"><a href="{e(d["url"])}" style="background:{ember};color:#fff;padding:10px 18px;'
        f'border-radius:99px;text-decoration:none;font-weight:bold">Open your deck</a></p></div>'
    )
    return "".join(parts)
