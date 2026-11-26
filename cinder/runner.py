"""Daily run pipeline (spec §4), spec worker (§6), swipes and undo."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from datetime import UTC, datetime
from typing import Awaitable, Callable

from . import agent
from .config import Config
from .db import DB, now
from .digest import refresh_digests, sync_repos
from .github import GitHub
from .notify import Notifier
from .scheduler import local_date, run_due

log = logging.getLogger("cinder.runner")

IDEATION_TIMEOUT = 30 * 60
SPEC_TIMEOUT = 15 * 60
SMALL_TIMEOUT = 5 * 60
KEEP_RUN_DIRS = 14


class UndoRefused(Exception):
    pass


def compute_slots(settings: dict, pending: list[dict]) -> tuple[int, int]:
    size = int(settings["deck_size"])
    mf, mp = int(settings["mix_features"]), int(settings["mix_projects"])
    pf = sum(1 for c in pending if c["kind"] == "feature")
    pp = sum(1 for c in pending if c["kind"] == "project")
    need = max(0, size - pf - pp)
    f, p = max(0, mf - pf), max(0, mp - pp)
    # Mix may not sum to the deck size: top up whichever type is furthest under target.
    while f + p < need:
        if (mf - pf - f) * max(mp, 1) >= (mp - pp - p) * max(mf, 1):
            f += 1
        else:
            p += 1
    # Trim to `need`, favouring whichever type is furthest under target (as a share of its target).
    while f + p > need:
        f_share = f / mf if mf else 0
        p_share = p / mp if mp else 0
        if (f_share < p_share and f > 0) or p == 0:
            f -= 1
        else:
            p -= 1
    return f, p


GitHubFactory = Callable[[], Awaitable[GitHub]]


class Cinder:
    def __init__(self, cfg: Config, db: DB, github_factory: GitHubFactory, notifier: Notifier, demo: bool = False):
        self.cfg = cfg
        self.demo = demo  # demo store: no agent calls, GitHub or email; Run now re-deals the demo deck
        self.db = db
        self.github_factory = github_factory
        self.notifier = notifier
        self.run_task: asyncio.Task | None = None
        self.run_id: int | None = None
        self.spec_wakeup = asyncio.Event()
        self.background: set[asyncio.Task] = set()
        self._run_lock = asyncio.Lock()

    # ---------- lifecycle ----------
    def recover(self) -> None:
        """After a restart, nothing is running: close out interrupted work."""
        self.db.run(
            "UPDATE runs SET status='failed', error='interrupted (Cinder restarted)', finished_at=? "
            "WHERE status='running'",
            (now(),),
        )
        self.db.run("UPDATE specs SET status='queued', updated_at=? WHERE status='writing'", (now(),))

    def spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self.background.add(task)
        task.add_done_callback(self.background.discard)
        return task

    async def shutdown(self) -> None:
        for t in list(self.background) + ([self.run_task] if self.run_task else []):
            t.cancel()
        await asyncio.gather(*self.background, return_exceptions=True)

    # ---------- runs ----------
    @property
    def running(self) -> bool:
        return self.run_task is not None and not self.run_task.done()

    async def start_run(self, kind: str) -> int:
        if self.demo:
            from .fixtures import reset_demo
            reset_demo(self.db)
            return 0
        async with self._run_lock:
            if self.running:
                return self.run_id
            run_id = self.db.run(
                "INSERT INTO runs(kind, status, step, started_at, local_date) VALUES(?,?,?,?,?)",
                (kind, "running", "starting", now(), local_date(self.db.settings()["tz"])),
            )
            self.run_id = run_id
            self.run_task = asyncio.create_task(self._run(run_id, kind))
            return run_id

    async def maybe_catch_up(self, wake: bool = False) -> int | None:
        if self.demo:
            return None
        if self.running:
            return self.run_id
        if run_due(self.db, self.db.settings(), wake=wake):
            return await self.start_run("daily")
        return None

    def _step(self, run_id: int, step: str) -> None:
        log.info("run %s: %s", run_id, step)
        self.db.run("UPDATE runs SET step=? WHERE id=?", (step, run_id))

    def _add_cost(self, run_id: int, cost: float) -> None:
        self.db.run("UPDATE runs SET cost_usd = cost_usd + ? WHERE id=?", (cost, run_id))

    async def _run(self, run_id: int, kind: str = "manual") -> None:
        try:
            new_cards, warning = await self.daily_pipeline(run_id)
            self.db.run(
                "UPDATE runs SET status='succeeded', step='done', finished_at=?, new_cards=?, error=? "
                "WHERE id=?",
                (now(), new_cards, warning, run_id),
            )
        except asyncio.CancelledError:
            self.db.run(
                "UPDATE runs SET status='failed', error='cancelled', finished_at=? WHERE id=?",
                (now(), run_id),
            )
            raise
        except Exception as exc:
            log.exception("run %s failed", run_id)
            if isinstance(exc, agent.AgentError):
                self._add_cost(run_id, exc.cost)
            step = (self.db.one("SELECT step FROM runs WHERE id=?", (run_id,)) or {}).get("step")
            self.db.run(
                "UPDATE runs SET status='failed', finished_at=?, error=? WHERE id=?",
                (now(), f"{(step or 'run').capitalize()} failed. {str(exc)[:500]}", run_id),
            )
        finally:
            self._prune_run_dirs()
        if kind == "daily":
            # One summary email per day, sent after the scheduled run whether it worked or not.
            await self.send_daily_summary()

    def summary_recipient(self) -> str:
        return (self.db.settings().get("notify_email") or self.cfg.notify_email or "").strip()

    async def send_daily_summary(self, force: bool = False, to: str | None = None) -> str:
        """Email the daily summary through AgentMail. Returns 'sent', 'skipped' or 'no-address'."""
        from . import summary
        to = to or self.summary_recipient()
        if not to:
            return "no-address"
        settings = self.db.settings()
        today = local_date(settings["tz"])
        if not force and settings.get("summary_sent_date") == today:
            return "skipped"
        data = summary.gather(self.db, self.cfg.base_url)
        try:
            await self.notifier.send(summary.subject(data), summary.render_text(data),
                                     html=summary.render_html(data), to=to)
        except Exception as exc:
            log.warning("daily summary not sent: %s", exc)
            if force:
                raise
            return "failed"
        if not force:
            self.db.set_settings({"summary_sent_date": today})
        return "sent"

    def _prune_run_dirs(self) -> None:
        root = self.cfg.runs_dir
        if not root.exists():
            return
        dirs = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime)
        for p in dirs[:-KEEP_RUN_DIRS]:
            shutil.rmtree(p, ignore_errors=True)

    async def daily_pipeline(self, run_id: int) -> tuple[int, str | None]:
        settings = self.db.settings()
        work = self.cfg.runs_dir / f"run-{run_id}"
        (work / "repos").mkdir(parents=True, exist_ok=True)

        self._step(run_id, "sync repos")
        gh = await self.github_factory()
        try:
            await sync_repos(self.db, gh)
            self._step(run_id, "build digests")
            repos = await refresh_digests(self.db, gh, int(settings["max_repos"]))
        finally:
            await gh.aclose()
        if not repos:
            raise RuntimeError("no repos to analyse (all excluded, or none accessible)")
        for r in repos:
            fname = r["full_name"].replace("/", "__") + ".md"
            (work / "repos" / fname).write_text(r["digest"] or f"# {r['full_name']}\n")

        self._step(run_id, "update profile")
        await self.update_profile(run_id)

        self._step(run_id, "compute slots")
        pending = self.db.all("SELECT kind FROM cards WHERE status='pending'")
        n_feat, n_proj = compute_slots(settings, pending)
        if n_feat + n_proj == 0:
            return 0, None

        self._step(run_id, "ideation")
        self._write_context(work)
        prompt = agent.render(
            "ideation",
            today=datetime.now(UTC).date().isoformat(),
            features=n_feat,
            projects=n_proj,
        )
        res = await agent.run_claude(
            self.cfg.claude_bin,
            prompt,
            agent.IDEATION_SCHEMA,
            tools=agent.WEB_TOOLS,
            budget=float(settings["budget_ideation"]),
            timeout=IDEATION_TIMEOUT,
            cwd=work,
        )
        self._add_cost(run_id, res.cost)

        self._step(run_id, "store cards")
        cards = self._accept_cards(res.data["cards"], {r["full_name"] for r in repos}, n_feat, n_proj)
        if not cards:
            raise RuntimeError("the agent returned no usable cards")
        with self.db.tx() as c:
            for card in cards:
                self.db.add_card(c, run_id, card)

        return len(cards), None

    def _write_context(self, work) -> None:
        profile = self.db.profile()["markdown"] or "(No profile yet: this developer hasn't swiped anything.)"
        (work / "profile.md").write_text(profile + "\n")
        rules = self.db.all("SELECT text FROM never_rules ORDER BY id")
        (work / "never_rules.md").write_text(
            "\n".join(f"- {r['text']}" for r in rules) + "\n" if rules else "(none)\n"
        )
        seen = self.db.all("SELECT kind, repo, title, payload_json FROM cards ORDER BY id")
        lines = []
        for s in seen:
            pitch = json.loads(s["payload_json"]).get("pitch", "")
            where = f" [{s['repo']}]" if s["repo"] else ""
            lines.append(f"- {s['title']}{where}: {pitch}")
        (work / "seen.md").write_text("\n".join(lines) + "\n" if lines else "(none yet)\n")
        deck = self.db.all("SELECT kind, repo, title FROM cards WHERE status='pending' ORDER BY value DESC")
        (work / "deck.md").write_text(
            "\n".join(f"- ({d['kind']}) {d['title']}" + (f" [{d['repo']}]" if d["repo"] else "") for d in deck)
            + "\n"
            if deck
            else "(empty)\n"
        )

    def _accept_cards(self, cards: list[dict], repo_names: set[str], n_feat: int, n_proj: int) -> list[dict]:
        by_lower = {n.lower(): n for n in repo_names}
        seen = {r["title"].strip().lower() for r in self.db.all("SELECT title FROM cards")}
        out, nf, np_ = [], 0, 0
        for card in sorted(cards, key=lambda c: -int(c.get("value", 0))):
            title = card["title"].strip()
            if not title or title.lower() in seen:
                continue
            if card["kind"] == "feature":
                repo = by_lower.get((card.get("repo") or "").strip().lower())
                if not repo or nf >= n_feat:
                    continue
                card["repo"] = repo
                nf += 1
            else:
                if np_ >= n_proj:
                    continue
                card.pop("repo", None)
                np_ += 1
            card["evidence"] = [e for e in card.get("evidence", []) if _safe_url(e.get("url", ""))]
            seen.add(title.lower())
            out.append(card)
        return out

    async def update_profile(self, run_id: int | None = None) -> None:
        prof = self.db.profile()
        swipes = self.db.all(
            "SELECT kind, repo, title, payload_json, status, note, never, decided_at FROM cards "
            "WHERE status != 'pending' AND decided_at > ? ORDER BY decided_at",
            (prof["swipes_through"] or "",),
        )
        if not swipes:
            return
        lines = []
        for s in swipes:
            p = json.loads(s["payload_json"])
            verdict = "SAVED" if s["status"] == "liked" else ("NEVER AGAIN" if s["never"] else "dismissed")
            where = f" [{s['repo']}]" if s["repo"] else ""
            line = f"- {verdict}: ({s['kind']}, effort {p.get('effort', '?')}) {s['title']}{where}: {p.get('pitch', '')}"
            if s["note"]:
                line += f'\n  Note: "{s["note"]}"'
            lines.append(line)
        settings = self.db.settings()
        res = await agent.run_claude(
            self.cfg.claude_bin,
            agent.render("profile", profile=prof["markdown"] or "(empty)", swipes="\n".join(lines)),
            agent.PROFILE_SCHEMA,
            tools="",
            budget=float(settings["budget_profile"]),
            timeout=SMALL_TIMEOUT,
            cwd=self.cfg.runs_dir / "profile",
        )
        if run_id:
            self._add_cost(run_id, res.cost)
        self.db.set_profile(res.data["markdown"].strip(), swipes[-1]["decided_at"])

    # ---------- swipes ----------
    def swipe(self, card_id: int, direction: str, note: str | None, never: bool) -> dict:
        note = (note or "").strip()[:4000] or None
        with self.db.tx() as c:
            row = c.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
            if not row:
                raise KeyError(card_id)
            if row["status"] != "pending":
                raise ValueError("card already decided")
            status = "liked" if direction == "right" else "dismissed"
            never = bool(never) and status == "dismissed"
            c.execute(
                "UPDATE cards SET status=?, decided_at=?, note=?, never=? WHERE id=?",
                (status, now(), note, int(never), card_id),
            )
            if status == "liked":
                c.execute(
                    "INSERT INTO specs(card_id, status, created_at, updated_at) VALUES(?,?,?,?) "
                    "ON CONFLICT(card_id) DO UPDATE SET status='queued', error=NULL, updated_at=excluded.updated_at",
                    (card_id, "queued", now(), now()),
                )
            rule_id = None
            if never:
                cur = c.execute(
                    "INSERT INTO never_rules(text, card_id, created_at) VALUES(?,?,?)",
                    (f"Ideas like: {row['title']}", card_id, now()),
                )
                rule_id = cur.lastrowid
        if status == "liked":
            self.spec_wakeup.set()
        if rule_id and not self.demo:
            self.spawn(self._refine_never_rule(rule_id, card_id))
        return {"status": status}

    def never_existing(self, card_id: int) -> int:
        """'Never like this' from the toast, after the card was already dismissed."""
        with self.db.tx() as c:
            row = c.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
            if not row or row["status"] != "dismissed":
                raise ValueError("only a dismissed card can become a never rule")
            if row["never"]:
                r = c.execute("SELECT id FROM never_rules WHERE card_id=?", (card_id,)).fetchone()
                return r["id"] if r else 0
            c.execute("UPDATE cards SET never=1 WHERE id=?", (card_id,))
            rule_id = c.execute(
                "INSERT INTO never_rules(text, card_id, created_at) VALUES(?,?,?)",
                (f"Ideas like: {row['title']}", card_id, now()),
            ).lastrowid
        if not self.demo:
            self.spawn(self._refine_never_rule(rule_id, card_id))
        return rule_id

    async def _refine_never_rule(self, rule_id: int, card_id: int) -> None:
        row = self.db.card(card_id)
        if not row:
            return
        p = json.loads(row["payload_json"])
        card_text = f"{row['kind']}: {row['title']}\n{p.get('pitch', '')}\n{p.get('summary', '')}"
        try:
            res = await agent.run_claude(
                self.cfg.claude_bin,
                agent.render("never_rule", card=card_text, note=row["note"] or "(none)"),
                agent.NEVER_RULE_SCHEMA,
                tools="",
                budget=float(self.db.settings()["budget_never_rule"]),
                timeout=SMALL_TIMEOUT,
                cwd=self.cfg.runs_dir / "never",
            )
        except Exception as exc:
            log.warning("never-rule refinement failed: %s", exc)
            return
        text = res.data["rule"].strip()
        if text:
            # Only overwrite the placeholder, never a rule the user edited.
            self.db.run(
                "UPDATE never_rules SET text=? WHERE id=? AND text LIKE 'Ideas like: %'", (text, rule_id)
            )

    def undo(self) -> dict:
        with self.db.tx() as c:
            row = c.execute(
                "SELECT * FROM cards WHERE status != 'pending' ORDER BY decided_at DESC LIMIT 1"
            ).fetchone()
            if not row:
                raise UndoRefused("Nothing to undo.")
            if row["status"] == "liked":
                spec = c.execute("SELECT status FROM specs WHERE card_id=?", (row["id"],)).fetchone()
                if spec and spec["status"] not in ("queued", "failed"):
                    raise UndoRefused(
                        "The spec for this idea is already being written, so it can't be undone. "
                        "You can close the PR instead."
                    )
                c.execute("DELETE FROM specs WHERE card_id=?", (row["id"],))
            c.execute("DELETE FROM never_rules WHERE card_id=?", (row["id"],))
            c.execute(
                "UPDATE cards SET status='pending', decided_at=NULL, note=NULL, never=0 WHERE id=?",
                (row["id"],),
            )
        return {"card_id": row["id"], "was": row["status"]}

    def resave(self, card_id: int, note: str | None) -> None:
        """Save a card that was dismissed earlier (from History)."""
        with self.db.tx() as c:
            row = c.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
            if not row or row["status"] != "dismissed":
                raise ValueError("only a dismissed card can be re-saved")
            c.execute(
                "UPDATE cards SET status='liked', decided_at=?, note=COALESCE(?, note), never=0 WHERE id=?",
                (now(), (note or "").strip() or None, card_id),
            )
            c.execute("DELETE FROM never_rules WHERE card_id=?", (card_id,))
            c.execute(
                "INSERT INTO specs(card_id, status, created_at, updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(card_id) DO UPDATE SET status='queued', error=NULL, updated_at=excluded.updated_at",
                (card_id, "queued", now(), now()),
            )
        self.spec_wakeup.set()

    def retry_spec(self, spec_id: int) -> None:
        n = self.db.run(
            "UPDATE specs SET status='queued', error=NULL, updated_at=? WHERE id=? AND status='failed'",
            (now(), spec_id),
        )
        if not n:
            raise ValueError("only a failed spec can be retried")
        self.spec_wakeup.set()

    # ---------- spec worker ----------
    async def spec_worker(self) -> None:
        while True:
            job = self.db.one("SELECT * FROM specs WHERE status='queued' ORDER BY updated_at, id LIMIT 1")
            if not job:
                self.spec_wakeup.clear()
                await self.spec_wakeup.wait()
                continue
            # Grace period: a just-saved card can still be undone before its spec starts.
            age = (datetime.now(UTC) - datetime.fromisoformat(job["updated_at"])).total_seconds()
            if age < self.cfg.spec_grace:
                self.spec_wakeup.clear()
                try:
                    await asyncio.wait_for(self.spec_wakeup.wait(), self.cfg.spec_grace - age)
                except asyncio.TimeoutError:
                    pass
                continue
            claimed = self.db.run(
                "UPDATE specs SET status='writing', updated_at=? WHERE id=? AND status='queued'",
                (now(), job["id"]),
            )
            if not claimed:
                continue
            try:
                url, cost = await self.write_spec(job)
                self.db.run(
                    "UPDATE specs SET status='pr_open', pr_url=?, cost_usd=cost_usd+?, error=NULL, updated_at=? "
                    "WHERE id=?",
                    (url, cost, now(), job["id"]),
                )
            except asyncio.CancelledError:
                self.db.run("UPDATE specs SET status='queued', updated_at=? WHERE id=?", (now(), job["id"]))
                raise
            except Exception as exc:
                log.exception("spec %s failed", job["id"])
                cost = exc.cost if isinstance(exc, agent.AgentError) else 0
                self.db.run(
                    "UPDATE specs SET status='failed', error=?, cost_usd=cost_usd+?, updated_at=? WHERE id=?",
                    (str(exc)[:500], cost, now(), job["id"]),
                )

    async def write_spec(self, job: dict) -> tuple[str, float]:
        card = self.db.card(job["card_id"])
        payload = json.loads(card["payload_json"])
        settings = self.db.settings()
        work = self.cfg.runs_dir / f"spec-{job['id']}"
        if work.exists():
            shutil.rmtree(work)
        (work / "files").mkdir(parents=True)
        (work / "profile.md").write_text((self.db.profile()["markdown"] or "(no profile yet)") + "\n")

        gh = await self.github_factory()
        try:
            if card["kind"] == "feature":
                repo = self.db.one("SELECT * FROM repos WHERE full_name=?", (card["repo"],))
                (work / "repo.md").write_text((repo or {}).get("digest") or f"# {card['repo']}\n")
                await self._fetch_relevant_files(gh, card["repo"], (repo or {}).get("default_branch"), payload, work)
                target_repo, path = card["repo"], f"docs/specs/{card['slug']}.md"
                hint = "(How it fits the existing code: modules to touch, data model changes, APIs.)"
            else:
                repos = self.db.all(
                    "SELECT digest FROM repos WHERE excluded=0 AND digest IS NOT NULL ORDER BY pushed_at DESC LIMIT 5"
                )
                (work / "repo.md").write_text("\n\n".join(r["digest"] for r in repos) or "(no repos)\n")
                target_repo, path = self.cfg.home_repo, f"docs/ideas/{card['slug']}.md"
                hint = "(Stack, architecture, and what can be reused from the developer's existing repos.)"

            card_text = _card_markdown(card, payload)
            res = await agent.run_claude(
                self.cfg.claude_bin,
                agent.render(
                    "spec",
                    today=datetime.now(UTC).date().isoformat(),
                    card=card_text,
                    note=card["note"] or "(none)",
                    title=card["title"],
                    technical_hint=hint,
                ),
                agent.SPEC_SCHEMA,
                tools=agent.WEB_TOOLS,
                budget=float(settings["budget_spec"]),
                timeout=SPEC_TIMEOUT,
                cwd=work,
            )
            doc = res.data["markdown"].strip()
            doc += "\n\n---\n\n## Appendix: original Cinder card\n\n" + card_text
            doc += "\n\n**Note from the owner:** " + (card["note"] or "_(none)_") + "\n"
            body = (
                f"{payload.get('pitch', '')}\n\n"
                + (f"**Owner's note:** {card['note']}\n\n" if card["note"] else "")
                + f"Spec written by Cinder from a saved idea card. File: `{path}`."
            )
            try:
                url = await gh.open_spec_pr(
                    target_repo, f"cinder/spec-{card['slug']}", path, doc, f"Spec: {card['title']}", body
                )
            except Exception as exc:
                raise RuntimeError(f"opening the PR failed: {exc}") from exc
            return url, res.cost
        finally:
            await gh.aclose()

    async def _fetch_relevant_files(self, gh: GitHub, repo: str, branch: str | None, payload: dict, work) -> None:
        """A shallow read: a few files whose paths share words with the idea."""
        try:
            files = await gh.tree(repo, branch or "main")
        except Exception as exc:
            log.info("tree failed for %s: %s", repo, exc)
            return
        words = {w for w in re.findall(r"[a-z]{4,}", (payload.get("title", "") + " " + payload.get("summary", "")).lower())}
        code_ext = (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".rb", ".swift", ".kt", ".java", ".md", ".toml", ".json")

        def score(path: str) -> int:
            p = path.lower()
            if not p.endswith(code_ext) or "/node_modules/" in p or p.startswith(("dist/", "build/", "vendor/")):
                return -1
            s = sum(3 for w in words if w in p)
            if p.count("/") <= 1:
                s += 1
            if any(k in p for k in ("app.", "main.", "index.", "server.", "routes", "api")):
                s += 1
            return s

        picks = [f for f in sorted(files, key=score, reverse=True) if score(f) > 0][:8]
        total = 0
        for f in picks:
            text = await gh.file_text(repo, f, ref=branch)
            if not text:
                continue
            text = text[:15000]
            total += len(text)
            dest = work / "files" / f
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text)
            if total > 60000:
                break


def _safe_url(url: str) -> bool:
    return url.startswith(("https://", "http://")) and len(url) < 2000


def _card_markdown(card: dict, p: dict) -> str:
    kind = f"Feature · `{card['repo']}`" if card["kind"] == "feature" else "New project"
    lines = [
        f"**{card['title']}** ({kind}, effort {p.get('effort', '?')})",
        "",
        p.get("pitch", ""),
        "",
        *[f"- {w}" for w in p.get("why", [])],
        "",
        f"**Summary:** {p.get('summary', '')}",
        f"**Why now:** {p.get('why_now', '')}",
        f"**SEO:** {p.get('seo', '')}",
        f"**AI-agent visibility:** {p.get('agent_visibility', '')}",
        f"**Competitors:** {'; '.join(p.get('competitors', [])) or '-'}",
        f"**Fit:** {p.get('fit', '')}",
        "**Evidence:**",
        *[f"- {e.get('claim', '')} ({e.get('url', '')})" for e in p.get("evidence", [])],
    ]
    return "\n".join(lines)
