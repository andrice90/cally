import json

from tests.conftest import ORIGIN, login, post, run_and_wait, wait_for


# ---------- auth & security ----------
def test_health_and_login_required(make_client):
    c = make_client()
    assert c.get("/healthz").json() == {"ok": True}
    assert c.get("/api/deck").status_code == 401
    r = c.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert "Content-Security-Policy" in c.get("/login").headers


def test_access_code_login(make_client):
    c = make_client()
    assert c.post("/auth/code", json={"code": "wrong"}, headers=ORIGIN).status_code == 401
    assert c.post("/auth/code", json={"code": c.app_cfg.access_code}).status_code == 403  # no Origin
    login(c)
    assert c.get("/api/me").status_code == 200
    assert c.get("/", follow_redirects=False).status_code == 200


def test_secrets_generated_and_private(env, make_client):
    c = make_client()
    envfile = c.app_cfg.home / "env"
    assert oct(envfile.stat().st_mode & 0o777) == "0o600"
    text = envfile.read_text()
    for k in ("CINDER_SESSION_SECRET", "CINDER_WAKE_TOKEN", "CINDER_ACCESS_CODE"):
        assert k in text


def test_write_protection(client):
    # Missing Origin, foreign Origin, non-JSON body: all refused.
    assert client.post("/api/runs", json={}).status_code == 403
    assert client.post("/api/runs", json={}, headers={"Origin": "https://evil.example"}).status_code == 403
    r = client.post("/api/runs", content="x", headers={**ORIGIN, "Content-Type": "text/plain"})
    assert r.status_code == 415


def test_oauth_only_owner(make_client, monkeypatch):
    import httpx
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_SECRET", "csecret")
    monkeypatch.setenv("CINDER_OWNER_LOGIN", "TheOwner")
    who = {"login": "someone-else"}

    def handler(req):
        if req.url.path == "/login/oauth/access_token":
            return httpx.Response(200, json={"access_token": "t"})
        return httpx.Response(200, json=who)

    c = make_client(oauth_transport=httpx.MockTransport(handler))
    assert c.get("/auth/options").json() == {"oauth": True, "code": False}
    assert c.post("/auth/code", json={"code": c.app_cfg.access_code}, headers=ORIGIN).status_code == 404
    r = c.get("/auth/login", follow_redirects=False)
    assert r.headers["location"].startswith("https://github.com/login/oauth/authorize")
    state = r.cookies.get("cinder_oauth_state") or c.cookies.get("cinder_oauth_state")
    # Bad state
    r = c.get("/auth/callback?code=x&state=nope", follow_redirects=False)
    assert "error=state" in r.headers["location"]
    # Wrong user
    r = c.get(f"/auth/callback?code=x&state={state}", follow_redirects=False)
    assert "error=denied" in r.headers["location"]
    # Owner (case-insensitive)
    c.get("/auth/login", follow_redirects=False)
    state = c.cookies.get("cinder_oauth_state")
    who["login"] = "theowner"
    r = c.get(f"/auth/callback?code=x&state={state}", follow_redirects=False)
    assert r.headers["location"] == "/"
    assert c.get("/api/me").json()["login"] == "theowner"


def test_wake_hook(client):
    assert client.post("/hooks/wake").status_code == 401
    assert client.post("/hooks/wake", headers={"Authorization": "Bearer nope"}).status_code == 401
    tok = client.app_cfg.wake_token
    with client.stream("POST", "/hooks/wake", headers={"Authorization": f"Bearer {tok}"}) as r:
        assert r.status_code == 200
        events = [json.loads(line) for line in r.iter_lines() if line]
    assert events[0]["event"] == "started"
    assert events[-1] == {"event": "finished", "status": "succeeded", "new_cards": 10, "error": None}
    # Today's run is done: a second wake does nothing.
    r = client.post("/hooks/wake", headers={"Authorization": f"Bearer {tok}"})
    assert json.loads(r.text.splitlines()[0])["event"] == "idle"


# ---------- daily run ----------
def test_daily_run_fills_deck(client, gh, mail, env):
    run = run_and_wait(client)
    assert run["status"] == "succeeded", run
    assert run["new_cards"] == 10
    deck = client.get("/api/deck").json()
    cards = deck["cards"]
    assert sum(c["kind"] == "feature" for c in cards) == 7
    assert sum(c["kind"] == "project" for c in cards) == 3
    assert "value" not in cards[0]  # never shown
    # Ordered by value: projects (90, 89, 88) first.
    assert [c["kind"] for c in cards[:3]] == ["project"] * 3
    # The fork is excluded by default, so no ideas for it.
    assert not any(c.get("repo") == "org/old-fork" for c in cards)
    # Unsafe evidence URLs are dropped.
    assert all(e["url"].startswith("http") for c in cards for e in c["evidence"])
    # Email sent.
    assert mail.sent and mail.sent[0]["subject"] == "Your Cinder deck is ready"
    assert mail.sent[0]["to"] == ["owner@example.com"]
    # The ideation call got web tools, never Bash/Edit/Write, and ran in the work dir.
    calls = [json.loads(l) for l in (env / "claude.log").read_text().splitlines()]
    ide = [c for c in calls if '"cards"' in c["argv"][c["argv"].index("--json-schema") + 1]][0]
    tools = ide["argv"][ide["argv"].index("--tools") + 1]
    assert tools == "WebSearch,WebFetch,Read,Glob,Grep"
    assert "/runs/run-" in ide["cwd"]


def test_second_run_only_tops_up(client):
    run_and_wait(client)
    deck = client.get("/api/deck").json()["cards"]
    feature = next(c for c in deck if c["kind"] == "feature")
    project = next(c for c in deck if c["kind"] == "project")
    post(client, f"/api/cards/{feature['id']}/swipe", {"direction": "left"})
    post(client, f"/api/cards/{project['id']}/swipe", {"direction": "left"})
    run = run_and_wait(client)
    assert run["new_cards"] == 2
    cards = client.get("/api/deck").json()["cards"]
    assert len(cards) == 10
    assert len({c["title"] for c in cards}) == 10
    # Third run: deck is full, so nothing new.
    assert run_and_wait(client)["new_cards"] == 0


def test_bad_agent_cards_filtered(client, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "badcards")
    run = run_and_wait(client)
    assert run["status"] == "succeeded"
    cards = client.get("/api/deck").json()["cards"]
    assert all(c.get("repo") != "someone/unknown" for c in cards)
    assert len(cards) == 10


def test_failed_run_keeps_deck(client, monkeypatch):
    run_and_wait(client)
    before = client.get("/api/deck").json()["cards"]
    post(client, f"/api/cards/{before[0]['id']}/swipe", {"direction": "left"})
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "garbage")
    run = run_and_wait(client)
    assert run["status"] == "failed" and "non-JSON" in run["error"]
    assert len(client.get("/api/deck").json()["cards"]) == 9


# ---------- swipes ----------
def test_swipe_right_opens_feature_spec_pr(client, gh):
    run_and_wait(client)
    card = next(c for c in client.get("/api/deck").json()["cards"] if c["kind"] == "feature")
    r = post(client, f"/api/cards/{card['id']}/swipe", {"direction": "right", "note": "Make it work offline"})
    assert r.json() == {"status": "liked"}

    def opened():
        s = client.get("/api/saved").json()["cards"]
        return s if s and s[0]["spec_status"] in ("pr_open", "failed") else None

    saved = wait_for(opened)[0]
    assert saved["spec_status"] == "pr_open", saved.get("spec_error")
    pr = gh.pulls[0]
    assert pr["repo"] == card["repo"]
    assert pr["head"] == f"cinder/spec-{card['slug']}"
    assert pr["title"] == f"Spec: {card['title']}"
    assert saved["pr_url"] == pr["html_url"]
    doc = gh.files[(card["repo"], pr["head"])][f"docs/specs/{card['slug']}.md"]
    assert "## Problem & opportunity" in doc
    assert "Make it work offline" in doc and "Appendix" in doc
    # Undo is refused once the spec has been written.
    r = post(client, "/api/undo")
    assert r.status_code == 409 and "already" in r.json()["error"]


def test_project_spec_goes_to_home_repo(client, gh):
    run_and_wait(client)
    card = next(c for c in client.get("/api/deck").json()["cards"] if c["kind"] == "project")
    post(client, f"/api/cards/{card['id']}/swipe", {"direction": "right"})
    wait_for(lambda: gh.pulls)
    assert gh.pulls[0]["repo"] == "owner/cinder"
    assert f"docs/ideas/{card['slug']}.md" in gh.files[("owner/cinder", f"cinder/spec-{card['slug']}")]


def test_dismiss_never_and_undo(client, env):
    run_and_wait(client)
    deck = client.get("/api/deck").json()["cards"]
    a = deck[0]
    r = post(client, f"/api/cards/{a['id']}/swipe", {"direction": "left", "note": "Too enterprise"})
    assert r.json() == {"status": "dismissed"}
    assert post(client, f"/api/cards/{a['id']}/swipe", {"direction": "left"}).status_code == 409
    rid = post(client, f"/api/cards/{a['id']}/never").json()["rule_id"]
    rules = wait_for(lambda: [r for r in client.get("/api/never-rules").json()["rules"]
                              if not r["text"].startswith("Ideas like")])
    assert rules[0]["id"] == rid and rules[0]["text"] == "No more ideas about things like that"
    # Undo restores the card, removes the rule, and puts it back in the deck.
    r = post(client, "/api/undo")
    assert r.json() == {"card_id": a["id"], "was": "dismissed"}
    assert client.get("/api/never-rules").json()["rules"] == []
    assert any(c["id"] == a["id"] for c in client.get("/api/deck").json()["cards"])
    # Undo with nothing decided.
    assert post(client, "/api/undo").status_code == 409


def test_never_rule_crud_and_ideation_input(client, env):
    run_and_wait(client)
    a = client.get("/api/deck").json()["cards"][0]
    post(client, f"/api/cards/{a['id']}/swipe", {"direction": "left", "never": True})
    rid = client.get("/api/never-rules").json()["rules"][0]["id"]
    assert client.put(f"/api/never-rules/{rid}", json={"text": "No CRMs"}, headers=ORIGIN).status_code == 200
    run_and_wait(client)
    log = [json.loads(l) for l in (env / "claude.log").read_text().splitlines()]
    ide_dir = [c["cwd"] for c in log if "/runs/run-" in c["cwd"]][-1]
    from pathlib import Path
    assert "No CRMs" in (Path(ide_dir) / "never_rules.md").read_text()
    assert a["title"] in (Path(ide_dir) / "seen.md").read_text()
    assert client.delete(f"/api/never-rules/{rid}", headers=ORIGIN).status_code == 200
    assert client.get("/api/never-rules").json()["rules"] == []


def test_undo_queued_like_cancels_spec(make_client, gh, monkeypatch):
    # With the real grace period, the spec worker waits, so an immediate undo succeeds.
    monkeypatch.setenv("CINDER_SPEC_GRACE", "30")
    client = login(make_client())
    run_and_wait(client)
    card = client.get("/api/deck").json()["cards"][0]
    post(client, f"/api/cards/{card['id']}/swipe", {"direction": "right"})
    import time; time.sleep(0.3)
    assert client.get("/api/saved").json()["cards"][0]["spec_status"] == "queued"
    assert post(client, "/api/undo").status_code == 200
    assert client.get("/api/saved").json()["cards"] == []
    assert gh.pulls == []


def test_undo_after_failed_spec(client, gh):
    run_and_wait(client)
    card = next(c for c in client.get("/api/deck").json()["cards"] if c["kind"] == "feature")
    gh.refs.pop((card["repo"], "main"))  # opening the PR will fail
    post(client, f"/api/cards/{card['id']}/swipe", {"direction": "right"})
    wait_for(lambda: client.get("/api/saved").json()["cards"][0]["spec_status"] == "failed")
    assert post(client, "/api/undo").status_code == 200


def test_history_and_resave(client, gh):
    run_and_wait(client)
    card = client.get("/api/deck").json()["cards"][0]
    post(client, f"/api/cards/{card['id']}/swipe", {"direction": "left", "note": "meh"})
    h = client.get("/api/history?filter=dismissed").json()["cards"]
    assert h[0]["id"] == card["id"] and h[0]["note"] == "meh"
    assert client.get("/api/history?filter=liked").json()["cards"] == []
    assert post(client, f"/api/cards/{card['id']}/resave").status_code == 200
    wait_for(lambda: gh.pulls)
    assert client.get("/api/history?filter=liked").json()["cards"][0]["id"] == card["id"]


def test_profile_learns_from_swipes(client, env):
    run_and_wait(client)
    deck = client.get("/api/deck").json()["cards"]
    post(client, f"/api/cards/{deck[0]['id']}/swipe", {"direction": "left", "note": "no B2B please"})
    post(client, f"/api/cards/{deck[1]['id']}/swipe", {"direction": "right"})
    run_and_wait(client)
    prof = client.get("/api/profile").json()
    assert "learned from 2 swipes" in prof["markdown"]
    log = [json.loads(l) for l in (env / "claude.log").read_text().splitlines()]
    prof_call = [c for c in log if "preference profile" in c["prompt"]][-1]
    assert 'Note: "no B2B please"' in prof_call["prompt"]
    assert prof_call["argv"][prof_call["argv"].index("--tools") + 1] == ""
    # No new swipes: the next run doesn't call the profile agent again.
    n = len([c for c in log if "preference profile" in c["prompt"]])
    run_and_wait(client)
    log = [json.loads(l) for l in (env / "claude.log").read_text().splitlines()]
    assert len([c for c in log if "preference profile" in c["prompt"]]) == n
    # Reset
    assert client.delete("/api/profile", headers=ORIGIN).status_code == 200
    assert client.get("/api/profile").json()["markdown"] == ""


# ---------- settings & repos ----------
def test_settings_and_repo_toggles(client, gh):
    assert post(client, "/api/repos/sync").json() == {"count": 5}
    repos = {r["full_name"]: r for r in client.get("/api/repos").json()["repos"]}
    assert repos["org/old-fork"]["excluded"] == 1
    assert repos["owner/alpha"]["excluded"] == 0
    r = client.put(f"/api/repos/{repos['owner/alpha']['id']}", json={"excluded": True}, headers=ORIGIN)
    assert r.status_code == 200
    post(client, "/api/repos/sync")  # re-sync keeps the user's choice
    repos = {r["full_name"]: r for r in client.get("/api/repos").json()["repos"]}
    assert repos["owner/alpha"]["excluded"] == 1
    run_and_wait(client)
    assert not any(c.get("repo") == "owner/alpha" for c in client.get("/api/deck").json()["cards"])

    s = client.put("/api/settings", json={"deck_size": 5, "mix_features": 3, "mix_projects": 2,
                                          "ready_by": "06:30", "tz": "Europe/London"}, headers=ORIGIN).json()
    assert s["deck_size"] == 5 and s["tz"] == "Europe/London"
    assert client.put("/api/settings", json={"tz": "Mars/Base"}, headers=ORIGIN).status_code == 422
    assert client.put("/api/settings", json={"ready_by": "25:00"}, headers=ORIGIN).status_code == 422


def test_digest_contents_and_cache(client, gh):
    run_and_wait(client)
    db = client.app.state.db
    d = db.one("SELECT digest FROM repos WHERE full_name='owner/alpha'")["digest"]
    assert "# owner/alpha" in d and "Initial commit" in d and "Bug one" in d and "package.json" in d
    assert "A PR" not in d  # pull requests aren't issues
    assert len(d) <= 4000
    n = sum(1 for m, p in gh.calls if p == "/repos/owner/alpha/readme")
    run_and_wait(client)
    assert sum(1 for m, p in gh.calls if p == "/repos/owner/alpha/readme") == n  # cached
