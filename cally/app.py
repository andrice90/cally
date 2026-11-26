"""FastAPI app: UI, JSON API, auth, wake hook."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import secrets
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode, urlparse

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel, Field

from .config import Config, load_config
from .db import DB
from .fixtures import reset_demo
from .github import GitHub
from .notify import Notifier
from .runner import Cally, UndoRefused
from .scheduler import next_ready

log = logging.getLogger("cally.app")
STATIC = Path(__file__).parent / "static"
SESSION_COOKIE = "cally_session"
STATE_COOKIE = "cally_oauth_state"
SESSION_AGE = 30 * 24 * 3600
TICK_SECONDS = 300
HEARTBEAT_SECONDS = 15


class RateLimit:
    def __init__(self, n: int, per: float):
        self.n, self.per, self.hits = n, per, deque()

    def allow(self) -> bool:
        t = time.monotonic()
        while self.hits and t - self.hits[0] > self.per:
            self.hits.popleft()
        if len(self.hits) >= self.n:
            return False
        self.hits.append(t)
        return True


# ---------- request bodies ----------
class SwipeIn(BaseModel):
    direction: Literal["left", "right"]
    note: str | None = Field(default=None, max_length=4000)
    never: bool = False


class NoteIn(BaseModel):
    note: str | None = Field(default=None, max_length=4000)


class RepoIn(BaseModel):
    excluded: bool


class RuleIn(BaseModel):
    text: str = Field(min_length=1, max_length=300)


class CodeIn(BaseModel):
    code: str = Field(max_length=200)


class SettingsIn(BaseModel):
    tz: str | None = None
    ready_by: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    deck_size: int | None = Field(default=None, ge=1, le=30)
    mix_features: int | None = Field(default=None, ge=0, le=30)
    mix_projects: int | None = Field(default=None, ge=0, le=30)
    max_repos: int | None = Field(default=None, ge=1, le=200)
    demo_mode: bool | None = None
    notify_email: str | None = Field(default=None, max_length=254, pattern=r"^$|^[^@\s]+@[^@\s]+\.[^@\s]+$")


def create_app(
    cfg: Config | None = None,
    github_factory=None,
    notifier: Notifier | None = None,
    oauth_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    cfg = cfg or load_config()
    db = DB(cfg.db_path)
    if github_factory is None:
        async def github_factory():
            return await GitHub.create(cfg)
    cally = Cally(cfg, db, github_factory, notifier or Notifier(cfg))
    # Demo mode: a separate database with generic content; no agent calls, GitHub or email.
    demo = Cally(cfg, DB(cfg.home / "demo.db"), github_factory, notifier or Notifier(cfg), demo=True)
    if not demo.db.one("SELECT 1 FROM cards LIMIT 1"):
        reset_demo(demo.db)

    def cur() -> Cally:
        return demo if db.settings().get("demo_mode") else cally
    signer = URLSafeTimedSerializer(cfg.session_secret, salt="cally-session")
    secure_cookie = cfg.base_url.startswith("https://")
    wake_limit = RateLimit(6, 3600)
    login_limit = RateLimit(10, 600)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        cally.recover()
        cally.spawn(cally.spec_worker())
        if cfg.scheduler:
            cally.spawn(ticker())
        yield
        await cally.shutdown()

    async def ticker():
        while True:
            try:
                await cally.maybe_catch_up()
            except Exception:
                log.exception("scheduler tick failed")
            await asyncio.sleep(TICK_SECONDS)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.cally = cally
    app.state.db = db

    # ---------- security plumbing ----------
    @app.middleware("http")
    async def headers(request: Request, call_next):
        try:
            resp = await call_next(request)
        except Exception:
            log.exception("unhandled error on %s", request.url.path)
            resp = JSONResponse({"error": "internal error"}, status_code=500)
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self' https://github.com"
        )
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith(("/api/", "/auth/", "/hooks/")):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    def current_user(request: Request) -> str | None:
        raw = request.cookies.get(SESSION_COOKIE)
        if not raw:
            return None
        try:
            data = signer.loads(raw, max_age=SESSION_AGE)
        except BadSignature:
            return None
        return data.get("u")

    def same_origin(request: Request) -> bool:
        origin = request.headers.get("origin")
        if not origin:
            return False
        o = urlparse(origin).netloc.lower()
        return o in {urlparse(cfg.base_url).netloc.lower(), (request.headers.get("host") or "").lower()}

    def require_user(request: Request) -> str:
        user = current_user(request)
        if not user:
            raise HTTPException(401, "sign in required")
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            if not same_origin(request):
                raise HTTPException(403, "bad origin")
            # A JSON content type can't be sent cross-site without a CORS preflight (DELETE has no body).
            if request.method != "DELETE" and "application/json" not in (request.headers.get("content-type") or ""):
                raise HTTPException(415, "JSON body required")
        return user

    def set_session(resp, user: str):
        resp.set_cookie(
            SESSION_COOKIE,
            signer.dumps({"u": user}),
            max_age=SESSION_AGE,
            httponly=True,
            secure=secure_cookie,
            samesite="lax",
            path="/",
        )

    # ---------- pages ----------
    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.get("/")
    async def index(request: Request):
        if not current_user(request):
            return RedirectResponse("/login", status_code=303)
        return FileResponse(STATIC / "index.html")

    @app.get("/login")
    async def login_page(request: Request):
        if current_user(request):
            return RedirectResponse("/", status_code=303)
        return FileResponse(STATIC / "login.html")

    @app.get("/sw.js")
    async def service_worker():
        return FileResponse(STATIC / "sw.js", media_type="text/javascript",
                            headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})

    @app.get("/manifest.webmanifest")
    async def manifest():
        return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    # ---------- auth ----------
    @app.get("/auth/options")
    async def auth_options():
        return {"oauth": cfg.oauth_enabled, "code": not cfg.oauth_enabled}

    @app.get("/auth/login")
    async def oauth_login():
        if not cfg.oauth_enabled:
            return RedirectResponse("/login", status_code=303)
        state = secrets.token_urlsafe(24)
        q = urlencode({
            "client_id": cfg.oauth_client_id,
            "redirect_uri": f"{cfg.base_url}/auth/callback",
            "scope": "read:user",
            "state": state,
            "allow_signup": "false",
        })
        resp = RedirectResponse(f"https://github.com/login/oauth/authorize?{q}", status_code=303)
        resp.set_cookie(STATE_COOKIE, state, max_age=600, httponly=True, secure=secure_cookie,
                        samesite="lax", path="/auth")
        return resp

    @app.get("/auth/callback")
    async def oauth_callback(request: Request, code: str = "", state: str = ""):
        expected = request.cookies.get(STATE_COOKIE) or ""
        if not cfg.oauth_enabled or not code or not state or not hmac.compare_digest(state, expected):
            return RedirectResponse("/login?error=state", status_code=303)
        if not login_limit.allow():
            return RedirectResponse("/login?error=rate", status_code=303)
        async with httpx.AsyncClient(timeout=20, transport=oauth_transport) as client:
            tok = await client.post(
                "https://github.com/login/oauth/access_token",
                data={"client_id": cfg.oauth_client_id, "client_secret": cfg.oauth_client_secret,
                      "code": code, "redirect_uri": f"{cfg.base_url}/auth/callback"},
                headers={"Accept": "application/json"},
            )
            access = (tok.json() if tok.status_code == 200 else {}).get("access_token")
            if not access:
                return RedirectResponse("/login?error=oauth", status_code=303)
            me = await client.get("https://api.github.com/user",
                                  headers={"Authorization": f"Bearer {access}", "Accept": "application/vnd.github+json"})
            login = (me.json() if me.status_code == 200 else {}).get("login", "")
        if not login or login.lower() != cfg.owner_login.lower():
            return RedirectResponse("/login?error=denied", status_code=303)
        resp = RedirectResponse("/", status_code=303)
        resp.delete_cookie(STATE_COOKIE, path="/auth")
        set_session(resp, login)
        return resp

    @app.post("/auth/code")
    async def code_login(request: Request, body: CodeIn):
        if cfg.oauth_enabled:
            raise HTTPException(404)
        if not same_origin(request):
            raise HTTPException(403, "bad origin")
        if not login_limit.allow():
            raise HTTPException(429, "too many attempts; try again later")
        if not cfg.access_code or not hmac.compare_digest(body.code.strip().encode(), cfg.access_code.encode()):
            raise HTTPException(401, "wrong code")
        resp = JSONResponse({"ok": True})
        set_session(resp, cfg.owner_login or "owner")
        return resp

    @app.post("/auth/logout")
    async def logout(request: Request):
        if not same_origin(request):
            raise HTTPException(403, "bad origin")
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(SESSION_COOKIE, path="/")
        return resp

    # ---------- API ----------
    def run_status() -> dict:
        r = cur().db.one("SELECT id, kind, status, step, started_at, finished_at, cost_usd, new_cards, error "
                   "FROM runs ORDER BY id DESC LIMIT 1")
        return r or {}

    @app.get("/api/me")
    async def me(user: str = Depends(require_user)):
        return {"login": user}

    @app.get("/api/deck")
    async def deck(user: str = Depends(require_user)):
        await cur().maybe_catch_up()
        s = db.settings()
        return {
            "cards": cur().db.deck(),
            "running": cur().running,
            "next_ready": next_ready(s["tz"], s["ready_by"]).isoformat(),
            "ready_by": s["ready_by"],
            "last_run": run_status(),
        }

    @app.post("/api/cards/{card_id}/swipe")
    async def swipe(card_id: int, body: SwipeIn, user: str = Depends(require_user)):
        try:
            return cur().swipe(card_id, body.direction, body.note, body.never)
        except KeyError:
            raise HTTPException(404, "no such card")
        except ValueError as exc:
            raise HTTPException(409, str(exc))

    @app.post("/api/cards/{card_id}/never")
    async def never(card_id: int, user: str = Depends(require_user)):
        try:
            return {"rule_id": cur().never_existing(card_id)}
        except ValueError as exc:
            raise HTTPException(409, str(exc))

    @app.post("/api/cards/{card_id}/resave")
    async def resave(card_id: int, body: NoteIn, user: str = Depends(require_user)):
        try:
            cur().resave(card_id, body.note)
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        return {"ok": True}

    @app.post("/api/undo")
    async def undo(user: str = Depends(require_user)):
        try:
            return cur().undo()
        except UndoRefused as exc:
            raise HTTPException(409, str(exc))

    @app.get("/api/saved")
    async def saved(user: str = Depends(require_user)):
        rows = cur().db.all(
            "SELECT c.*, s.id AS spec_id, s.status AS spec_status, s.pr_url, s.error AS spec_error "
            "FROM cards c LEFT JOIN specs s ON s.card_id = c.id WHERE c.status='liked' ORDER BY c.decided_at DESC"
        )
        return {"cards": [cur().db.card_out(r) for r in rows]}

    @app.get("/api/history")
    async def history(filter: Literal["all", "liked", "dismissed"] = "all", user: str = Depends(require_user)):
        where = "c.status != 'pending'" if filter == "all" else "c.status = ?"
        args = () if filter == "all" else (filter,)
        rows = cur().db.all(
            "SELECT c.*, s.status AS spec_status, s.pr_url FROM cards c LEFT JOIN specs s ON s.card_id=c.id "
            f"WHERE {where} ORDER BY c.decided_at DESC LIMIT 500",
            args,
        )
        return {"cards": [cur().db.card_out(r) for r in rows]}

    @app.post("/api/specs/{spec_id}/retry")
    async def retry(spec_id: int, user: str = Depends(require_user)):
        try:
            cur().retry_spec(spec_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        return {"ok": True}

    @app.get("/api/settings")
    async def get_settings(user: str = Depends(require_user)):
        s = db.settings()
        return {k: s[k] for k in ("tz", "ready_by", "deck_size", "mix_features", "mix_projects", "max_repos", "demo_mode", "notify_email")}

    @app.put("/api/settings")
    async def put_settings(body: SettingsIn, user: str = Depends(require_user)):
        values = body.model_dump(exclude_none=True)
        if "tz" in values:
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
            try:
                ZoneInfo(values["tz"])
            except (ZoneInfoNotFoundError, ValueError):
                raise HTTPException(422, "unknown time zone")
        if values.get("demo_mode") and not db.settings().get("demo_mode"):
            reset_demo(demo.db)  # every demo starts from a fresh deck
        db.set_settings(values)
        return await get_settings(user)

    @app.post("/api/summary/test")
    async def summary_test(user: str = Depends(require_user)):
        to = cally.summary_recipient()
        if not to:
            raise HTTPException(409, "Add an email address first.")
        try:
            await cur().send_daily_summary(force=True, to=to)
        except Exception as exc:
            raise HTTPException(502, f"Email not sent. {str(exc)[:200]}")
        return {"ok": True}

    @app.post("/api/demo/reset")
    async def demo_reset(user: str = Depends(require_user)):
        reset_demo(demo.db)
        return {"ok": True}

    @app.get("/api/repos")
    async def repos(user: str = Depends(require_user)):
        rows = cur().db.all("SELECT id, full_name, description, pushed_at, archived, fork, private, excluded, "
                      "digest IS NOT NULL AS has_digest FROM repos ORDER BY pushed_at DESC")
        return {"repos": rows}

    @app.post("/api/repos/sync")
    async def repos_sync(user: str = Depends(require_user)):
        from .digest import sync_repos
        if cur().demo:
            return {"count": len(demo.db.all("SELECT id FROM repos"))}
        try:
            gh = await github_factory()
        except Exception as exc:
            raise HTTPException(503, str(exc)[:300])
        try:
            n = await sync_repos(db, gh)
        except Exception as exc:
            raise HTTPException(502, str(exc)[:300])
        finally:
            await gh.aclose()
        return {"count": n}

    @app.put("/api/repos/{repo_id}")
    async def put_repo(repo_id: int, body: RepoIn, user: str = Depends(require_user)):
        n = cur().db.run("UPDATE repos SET excluded=?, excluded_set=1 WHERE id=?", (int(body.excluded), repo_id))
        if not n:
            raise HTTPException(404, "no such repo")
        return {"ok": True}

    @app.get("/api/profile")
    async def profile(user: str = Depends(require_user)):
        p = cur().db.profile()
        return {"markdown": p["markdown"], "updated_at": p["updated_at"]}

    @app.delete("/api/profile")
    async def reset_profile(user: str = Depends(require_user)):
        # Reset forgets learned preferences, including swipes made so far.
        latest = cur().db.one("SELECT MAX(decided_at) AS t FROM cards") or {}
        cur().db.set_profile("", latest.get("t") or "")
        return {"ok": True}

    @app.get("/api/never-rules")
    async def rules(user: str = Depends(require_user)):
        return {"rules": cur().db.all("SELECT id, text, card_id, created_at FROM never_rules ORDER BY id DESC")}

    @app.get("/api/never-rules/{rule_id}")
    async def rule(rule_id: int, user: str = Depends(require_user)):
        r = cur().db.one("SELECT id, text, card_id, created_at FROM never_rules WHERE id=?", (rule_id,))
        if not r:
            raise HTTPException(404)
        return r

    @app.put("/api/never-rules/{rule_id}")
    async def edit_rule(rule_id: int, body: RuleIn, user: str = Depends(require_user)):
        if not cur().db.run("UPDATE never_rules SET text=? WHERE id=?", (body.text.strip(), rule_id)):
            raise HTTPException(404)
        return {"ok": True}

    @app.delete("/api/never-rules/{rule_id}")
    async def delete_rule(rule_id: int, user: str = Depends(require_user)):
        cur().db.run("UPDATE cards SET never=0 WHERE id=(SELECT card_id FROM never_rules WHERE id=?)", (rule_id,))
        if not cur().db.run("DELETE FROM never_rules WHERE id=?", (rule_id,)):
            raise HTTPException(404)
        return {"ok": True}

    @app.post("/api/runs")
    async def run_now(user: str = Depends(require_user)):
        run_id = await cur().start_run("manual")
        return {"run_id": run_id}

    @app.get("/api/runs/latest")
    async def runs_latest(user: str = Depends(require_user)):
        recent = cur().db.all("SELECT id, kind, status, step, started_at, finished_at, cost_usd, new_cards, error "
                        "FROM runs ORDER BY id DESC LIMIT 10")
        return {"latest": recent[0] if recent else None, "recent": recent, "running": cur().running}

    # ---------- wake hook ----------
    @app.post("/hooks/wake")
    async def wake(request: Request):
        auth = request.headers.get("authorization") or ""
        token = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
        if not cfg.wake_token or not hmac.compare_digest(token.encode(), cfg.wake_token.encode()):
            raise HTTPException(401, "bad token")
        if not wake_limit.allow():
            raise HTTPException(429, "rate limited")
        run_id = await cally.maybe_catch_up(wake=True)

        async def stream():
            if run_id is None:
                yield json.dumps({"event": "idle", "detail": "today's run already done"}) + "\n"
                return
            yield json.dumps({"event": "started", "run_id": run_id}) + "\n"
            task = cally.run_task
            while task and not task.done():
                done, _ = await asyncio.wait({task}, timeout=HEARTBEAT_SECONDS)
                if not done:
                    r = db.one("SELECT step FROM runs WHERE id=?", (run_id,)) or {}
                    yield json.dumps({"event": "heartbeat", "step": r.get("step")}) + "\n"
            # Keep the Sprite awake while any queued specs finish too.
            while db.one("SELECT 1 FROM specs WHERE status IN ('queued','writing') LIMIT 1"):
                await asyncio.sleep(HEARTBEAT_SECONDS)
                yield json.dumps({"event": "heartbeat", "step": "specs"}) + "\n"
            r = db.one("SELECT status, new_cards, error FROM runs WHERE id=?", (run_id,)) or {}
            yield json.dumps({"event": "finished", "status": r.get("status"), "new_cards": r.get("new_cards"),
                              "error": r.get("error")}) + "\n"

        return StreamingResponse(stream(), media_type="application/x-ndjson",
                                 headers={"X-Accel-Buffering": "no"})

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    return app
