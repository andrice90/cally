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
    return "Cally: " + ", ".join(parts)


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


# Email styling mirrors the app's index cards: warm paper, rounded card, serif ink, ember accent.
PAPER, CARD, INK, INK2, FAINT, LINE = "#f4eee6", "#fffdf9", "#2a211b", "#5b4d43", "#9a8a7d", "#e4d9cb"
EMBER, EMBER_SOFT, BAD = "#d9481a", "#fde7da", "#b8322a"
SERIF = "'Iowan Old Style','Palatino Linotype',Palatino,'Book Antiqua',Georgia,serif"
SHADOW = "0 1px 1px rgba(70,45,25,.05),0 4px 8px rgba(70,45,25,.06),0 16px 32px rgba(70,45,25,.10)"
WORDMARK_CID = "cally-wordmark"


def attachments() -> list[dict]:
    """The wordmark, attached inline (cid) so it shows without remote image loading."""
    import base64
    from pathlib import Path
    png = (Path(__file__).parent / "static" / "wordmark-email.png").read_bytes()
    return [{
        "filename": "cally.png", "content_type": "image/png", "content_disposition": "inline",
        "content_id": WORDMARK_CID, "content": base64.b64encode(png).decode(),
    }]


def _card(chip: str, count: str, title: str, pitch: str, rows: list[str], foot: str = "", extra: str = "") -> str:
    e = html.escape
    top = (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
        f'<td align="left"><span style="display:inline-block;background:{EMBER_SOFT};color:{INK2};font-style:italic;'
        f'font-size:14px;padding:6px 12px;border-radius:99px">{e(chip)}</span></td>'
        f'<td align="right" width="40"><div style="width:37px;height:37px;line-height:37px;text-align:center;'
        f'border-radius:50%;border:1.5px solid {LINE};font-weight:bold;font-size:16px;color:{INK}">{e(count)}</div></td>'
        "</tr></table>"
    )
    face = (
        f'<div style="text-align:center;padding:28px 4px 20px">'
        f'<div style="font-size:32px;line-height:1.12;font-weight:bold;letter-spacing:-.01em;color:{INK}">{e(title)}</div>'
        f'<div style="width:44px;height:2px;background:{LINE};border-radius:2px;margin:16px auto;font-size:0;line-height:0">&nbsp;</div>'
        f'<div style="font-size:18px;line-height:1.45;font-style:italic;color:{INK2}">{e(pitch)}</div></div>'
    )
    body = ""
    if rows:
        body = f'<div style="border-top:1px dashed {LINE};padding-top:8px">' + "".join(rows) + "</div>"
    if foot:
        body += f'<div style="margin-top:16px;text-align:center;color:{FAINT};font-size:13px;font-style:italic">{e(foot)}</div>'
    body += extra
    return (
        f'<tr><td style="background:{CARD};border-radius:34px;box-shadow:{SHADOW};border:1px solid #efe6da;'
        f'padding:24px 24px 24px">{top}{face}{body}</td></tr><tr><td style="height:20px;font-size:0;line-height:0">&nbsp;</td></tr>'
    )


def _row(title_html: str, meta: str = "") -> str:
    m = f'<div style="font-size:13px;font-style:italic;color:{FAINT};margin-top:2px">{html.escape(meta)}</div>' if meta else ""
    return f'<div style="padding:8px 0;font-size:15px;line-height:1.35;color:{INK}">{title_html}{m}</div>'


def render_html(d: dict) -> str:
    e = html.escape
    n, k = len(d["waiting"]), len(d["opened"])
    cards = []
    problem = _run_line(d)
    if problem:
        cards.append(
            f'<tr><td style="background:#f9e1de;border-radius:24px;padding:16px 20px;color:{BAD};font-size:15px">'
            f'{e(problem)}</td></tr><tr><td style="height:20px;font-size:0;line-height:0">&nbsp;</td></tr>'
        )
    # Today's deck
    rows = [
        _row(f"<b>{e(w['title'])}</b>", f"{_where(w)} · {EFFORT.get(w['effort'], w['effort'])}" + (" · new" if w["new"] else ""))
        for w in d["waiting"]
    ]
    pitch = (f"{d['new_today']} new this morning." if d["new_today"] else "Nothing new this morning.") if n else "You're all caught up."
    button = (
        f'<div style="text-align:center;padding-top:20px"><a href="{e(d["url"])}" style="display:inline-block;'
        f'background:{EMBER};color:#ffffff;font-weight:bold;font-size:17px;padding:14px 28px;border-radius:99px;'
        f'text-decoration:none">Open your deck</a></div>'
    )
    cards.append(_card("Today's deck", str(n), f"{n} idea{'s' if n != 1 else ''} waiting", pitch, rows, extra=button))
    # Yesterday
    spec_rows = []
    for o in d["opened"]:
        url = _safe_url(o["pr_url"])
        link = f' <a href="{e(url)}" style="color:{EMBER};font-style:italic;text-decoration:none">View PR</a>' if url else ""
        spec_rows.append(_row(f"{e(o['title'])}{link}", _where(o)))
    for f in d["failed"]:
        spec_rows.append(_row(f'{e(f["title"])} <span style="color:{BAD};font-style:italic">failed</span>'))
    foot = f"{d['runs']} run{'s' if d['runs'] != 1 else ''}, ${d['cost']:.2f}" if d["runs"] else ""
    title = f"{k} new spec{'s' if k != 1 else ''}" if k else "No new specs"
    cards.append(_card("Yesterday", str(k), title, _activity_line(d), spec_rows, foot))
    return (
        f'<!DOCTYPE html><html><head><meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light"></head>'
        f'<body style="margin:0;padding:0;background:{PAPER}">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{PAPER}" style="background:{PAPER}">'
        f'<tr><td align="center" style="padding:28px 14px 40px;font-family:{SERIF};color:{INK}">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px">'
        f'<tr><td align="center" style="padding:0 0 20px"><img src="cid:{WORDMARK_CID}" width="84" height="68" alt="cally" '
        f'style="display:block;border:0"></td></tr>'
        + "".join(cards)
        + "</table></td></tr></table></body></html>"
    )
