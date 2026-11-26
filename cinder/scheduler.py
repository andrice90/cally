"""When is a daily run due? (spec §8)"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

MAX_ATTEMPTS_PER_DAY = 3
RETRY_AFTER = timedelta(minutes=30)


def local_now(tz: str, now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)).astimezone(ZoneInfo(tz))


def local_date(tz: str, now: datetime | None = None) -> str:
    return local_now(tz, now).date().isoformat()


def generation_time(tz: str, ready_by: str, lead_minutes: int, now: datetime | None = None) -> datetime:
    """Today's generation start, as an aware datetime in the configured zone."""
    loc = local_now(tz, now)
    hh, mm = (int(x) for x in ready_by.split(":"))
    ready = loc.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return ready - timedelta(minutes=lead_minutes)


def next_ready(tz: str, ready_by: str, now: datetime | None = None) -> datetime:
    loc = local_now(tz, now)
    hh, mm = (int(x) for x in ready_by.split(":"))
    ready = loc.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return ready if ready > loc else ready + timedelta(days=1)


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def run_due(db, settings: dict, *, wake: bool = False, now: datetime | None = None) -> bool:
    """True if today's run hasn't succeeded and we should start one now.

    `wake` (the scheduled trigger) may start a run any time of day; catch-up (app opened, background
    tick) waits until today's generation time.
    """
    now = now or datetime.now(UTC)
    tz = settings["tz"]
    today = local_date(tz, now)
    if not wake:
        gen = generation_time(tz, settings["ready_by"], int(settings["generate_lead_minutes"]), now)
        if now < gen:
            return False
    runs = db.all(
        "SELECT status, started_at, finished_at FROM runs WHERE local_date=? ORDER BY id", (today,)
    )
    if any(r["status"] in ("succeeded", "running") for r in runs):
        return False
    failed = [r for r in runs if r["status"] == "failed"]
    if len(failed) >= MAX_ATTEMPTS_PER_DAY:
        return False
    if failed and not wake:
        last = _parse(failed[-1]["finished_at"] or failed[-1]["started_at"])
        if now - last < RETRY_AFTER:
            return False
    return True
