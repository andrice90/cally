# Cinder — Product & Technical Spec

> Status: approved for build (v1). Lives in this repo (`andrice90/cinder`, formerly `andrice90/fly-agent`).

## 1. What Cinder is

Cinder is a personal agent that reads all of your GitHub repos and, every morning, deals you a deck of
**10 idea cards**: new features for projects you already have, and new project ideas that build on what
you're already making. Ideas are researched against the current market, SEO, AI-agent visibility, and
trends, then ordered from most to least valuable.

You work through the deck on your phone or in a browser:

| Gesture | Meaning |
|---|---|
| **Swipe left** | Dismiss |
| **Swipe right** | Save → Cinder writes a full product spec and opens a PR with it |
| **Swipe up** | Add a note, then swipe left or right (the note goes with the decision) |

Every swipe and note feeds a preference profile, so the next day's ideas fit your taste better.

## 2. Decisions (agreed)

| Topic | Decision |
|---|---|
| Users | Single user (the owner). Not multi-tenant. |
| Repos analysed | Everything the configured GitHub credential can access. Individual repos can be excluded in Settings. |
| Cinder's own code | This repo. |
| Deck size | Up to **10 cards**: target mix **7 features / 3 new projects**. |
| Unswiped cards | **Persist** indefinitely. Each daily run only adds new cards to bring the deck back up to 10. |
| Deck ready by | **7:00 am Central** (`America/Chicago`, which follows CDT/CST). Generation starts ~5:00 am. |
| Value | A mix of revenue/market potential, effort, fit with existing work, timing/trends. **No score shown**; cards are simply ordered most valuable first. |
| "ASO" | **AI-agent visibility**: being found and recommended by AI assistants and agents (e.g. llms.txt, structured docs, MCP servers, agent-readable APIs, presence in LLM answers). Not app-store optimisation. |
| Research data | Claude's built-in web search/fetch for v1. No paid SEO data yet. |
| Agent | `claude` CLI in print mode, logged in with the owner's Claude subscription. Anthropic API is available as a fallback if needed. |
| Feature specs | PR to the **target repo**, file `docs/specs/<slug>.md`. |
| New-project specs | PR to **this (Cinder) repo**, file `docs/ideas/<slug>.md`. Option later to promote one to a real repo. |
| Spec scope | Spec only. No GitHub issues, no implementation. |
| Notes on swipes | On a right swipe → direction for the spec. On a left swipe → reason for passing (training signal). |
| Extras | **Undo** last swipe; **"Never suggest things like this"** on dismiss. |
| App login | GitHub OAuth, restricted to the owner's GitHub account. |
| Morning alert | Daily summary email via the AgentMail Sprites connector after the scheduled run: what's waiting today, yesterday's new specs, and yesterday's activity. Recipient set in Settings. |

## 3. User experience

### 3.1 Deck (home screen)
- A stack of cards, top card fully visible, next card peeking behind it.
- Drag with finger/mouse: card follows and tilts; release past a threshold commits the swipe, otherwise it springs back.
- Buttons under the stack for the same actions (✕ dismiss, ✎ note, ♥ save) plus ↶ undo. Keyboard: ←, →, ↑, `u`.
- After a dismiss, a toast: **Dismissed · Undo · Never like this**.
- Swipe up opens a notes sheet over the card. Saving the note returns the card to the stack with a "note attached" marker; the user then swipes left or right.
- Empty state: "You're all caught up — next deck at 7:00 am" plus a **Run now** button.

### 3.2 Card content
Front (what's visible while swiping):
- Type badge: **Feature · `repo-name`** or **New project**
- Title (≤ 70 chars)
- One-line pitch
- 3 short "why" bullets (market signal, trend, fit with existing work)
- Effort: S / M / L

Tap to expand (details panel):
- Summary (a paragraph)
- Why now (trends, timing)
- SEO angle (keywords/intent, content opportunities)
- AI-agent visibility angle
- Competitors / prior art
- Evidence list: claim + source link
- Fit: which repos/skills it builds on

### 3.3 Saved
- List of right-swiped cards with spec status: `queued → writing → PR open (link) | failed (retry)`.

### 3.4 History
- Everything swiped, filterable by liked/dismissed, with notes. Lets the user re-save a dismissed card.

### 3.5 Settings
- Repos: list with include/exclude toggles (default: included).
- Schedule: time zone and ready-by time (default `America/Chicago`, 07:00).
- Deck size and mix (default 10, 7/3).
- "Never like this" rules: view/remove.
- Preference profile: read-only view of what Cinder thinks you like (with a reset button).
- Last run status + logs summary + **Run now**.

### 3.6 Look
- Original "ember" visual identity (warm dark theme, orange/red accent). Generic swipe mechanic; no imitation of any existing app's branding.
- Mobile-first, installable as a PWA (home-screen icon, full-screen).

## 4. Daily run pipeline

Triggered at ~5:00 am Central (see §8). One run at a time (lock in DB).

1. **Sync repos** via GitHub API: list all accessible repos (`/user/repos?affiliation=owner,collaborator,organization_member`, falling back to `/installation/repositories` for app tokens). Store metadata. Skip excluded repos. Archived repos and forks are listed but excluded by default.
2. **Build repo digests** (cached; rebuilt only when `pushed_at` changes). Per repo, ≤ ~4k chars:
   - name, description, topics, languages, stars, last push
   - README (truncated)
   - top-level file tree + key manifests (`package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, etc.)
   - last ~20 commit messages
   - open issue titles (≤ 20)
   - Prioritise the ~25 most recently active repos if there are many (configurable).
   - Digests are written as files to a per-run work directory the agent can read.
3. **Update preference profile** (small agent call, no tools): take the current profile + all swipes/notes since the last update → rewrite the profile (§5).
4. **Compute slots**: `need = 10 − pending`. Target new features = `max(0, 7 − pending_features)`, projects = `max(0, 3 − pending_projects)`; trim to `need`, favouring whichever type is furthest under target. If `need == 0`, skip ideation.
5. **Ideation + research** (main agent call, web tools): input = profile, "never" rules, titles of every card ever shown (for de-duplication), pending deck, digests, slot counts. The agent researches market, SEO, AI-agent visibility and trends, generates candidates, and returns structured cards (§7.3) each with a hidden `value` (0–100) used only for ordering.
6. **Store cards**; deck order = `value` descending across all pending cards.
7. **Notify**: email via AgentMail with the count of new cards and a link.
8. Record run: start/end, cost reported by the CLI, card counts, errors.

Failure handling: a failed step marks the run failed with a reason and leaves the existing deck untouched. The next wake retries if today's run hasn't succeeded.

## 5. Learning loop

No model training. Cinder keeps:
- **Swipe log**: every card, decision, note, timestamp.
- **Preference profile**: a markdown document (≤ ~1.5k words) the agent rewrites from the swipe log, e.g. liked themes, disliked themes, preferred effort sizes, favourite repos, monetisation preferences, explicit quotes from notes.
- **Never rules**: short descriptions created from "Never like this" (the agent turns the card into a one-line rule; user can edit/remove).
- **Seen list**: titles + one-liners of every card ever shown, so ideas aren't repeated.

All four are given to the ideation call. Notes are weighted more heavily than bare swipes.

## 6. Spec generation (swipe right)

Queued immediately on save; a worker processes jobs one at a time.

1. Agent call (web tools + read access to the repo digest; for features, also a shallow read of relevant files fetched via the API) with the card, the user's note (if any) and the profile.
2. Output: markdown spec with sections:
   - Problem & opportunity
   - Target users
   - Market evidence (with sources)
   - SEO & AI-agent visibility plan
   - Proposed solution & scope (in / out)
   - User stories
   - Technical approach (for features: how it fits the existing code)
   - Milestones / task breakdown
   - Success metrics
   - Risks & open questions
   - Appendix: the original card + user note
3. **Cinder's code** (not the agent) commits it via the GitHub API: create branch `cinder/spec-<slug>`, add the file (§2), open a PR titled `Spec: <title>`, store the PR URL on the card.

## 7. Architecture

### 7.1 Stack
- **Backend**: Python 3.13, FastAPI + Uvicorn, SQLite (WAL) via the standard library or SQLAlchemy Core. Background work runs as asyncio tasks in the same process.
- **Frontend**: plain HTML/CSS/JavaScript with no build step, served by FastAPI. Swipes via Pointer Events. PWA manifest + service worker (app shell only; no offline writes in v1).
- **Agent**: `claude` CLI launched with `asyncio.create_subprocess_exec`.
- **One Sprite service** (`cinder`) on port **8080**, serving the UI, `/api/*`, and the trigger endpoint. (The Sprite only exposes one port.)

### 7.2 Layout
```
cinder/            Python package
  app.py           FastAPI app, routes, auth
  db.py            schema + queries
  github.py        GitHub client (Sprite gateway or token)
  digest.py        repo digests
  agent.py         claude CLI wrapper, prompts, JSON schemas
  runner.py        daily run pipeline + spec worker
  scheduler.py     due-run checks
  notify.py        AgentMail email
  static/          index.html, app.js, app.css, manifest, icons, sw.js
  prompts/         ideation.md, profile.md, spec.md, never_rule.md
docs/SPEC.md       this file
tests/             pytest (fake GitHub + fake claude binary)
.github/workflows/cinder-wake.yml
```
Runtime data lives **outside the repo** in `~/.cinder/`: `cinder.db`, `env` (secrets, chmod 600), `runs/<id>/` work dirs, logs.

### 7.3 Card schema (agent output, via `--json-schema`)
```json
{
  "cards": [{
    "kind": "feature | project",
    "repo": "owner/name (features only)",
    "title": "string",
    "pitch": "string",
    "why": ["string", "string", "string"],
    "effort": "S | M | L",
    "summary": "string",
    "why_now": "string",
    "seo": "string",
    "agent_visibility": "string",
    "competitors": ["string"],
    "evidence": [{"claim": "string", "url": "string"}],
    "fit": "string",
    "value": 0
  }]
}
```

### 7.4 Data model (SQLite)
- `repos(id, full_name, description, default_branch, pushed_at, archived, fork, excluded, digest, digest_pushed_at)`
- `cards(id, run_id, kind, repo, slug, title, payload_json, value, status[pending|liked|dismissed], created_at, decided_at, note, never)`
- `specs(id, card_id, status[queued|writing|pr_open|failed], pr_url, error, cost_usd, created_at, updated_at)`
- `runs(id, kind[daily|manual], status, started_at, finished_at, cost_usd, new_cards, error)`
- `profile(id, markdown, updated_at, swipes_through)` (`swipes_through` = `decided_at` of the last swipe folded in, since cards are decided out of id order)
- `never_rules(id, text, card_id, created_at)`
- `settings(key, value)`
- `swipe_undo` handled by reverting the most recent decision (only while its spec job is still `queued`; otherwise undo is refused with an explanation).

### 7.5 HTTP API
| Method & path | Purpose |
|---|---|
| `GET /` | App shell (redirects to login if needed) |
| `GET /auth/login`, `/auth/callback`, `POST /auth/logout` | GitHub OAuth |
| `GET /api/deck` | Pending cards in value order |
| `POST /api/cards/{id}/swipe` | `{direction: left|right, note?, never?}` |
| `POST /api/cards/{id}/never` | "Never like this" from the toast after a dismiss |
| `POST /api/cards/{id}/resave` | Save a previously dismissed card (History) |
| `POST /api/undo` | Undo last swipe |
| `GET /api/saved`, `GET /api/history` | Lists |
| `POST /api/specs/{id}/retry` | Retry a failed spec |
| `GET/PUT /api/settings`, `GET /api/repos`, `PUT /api/repos/{id}`, `POST /api/repos/sync` | Settings, repo toggles, repo list refresh |
| `GET /api/profile`, `DELETE /api/profile` | View / reset profile |
| `GET /api/never-rules`, `GET/PUT/DELETE /api/never-rules/{id}` | Manage never rules |
| `POST /api/runs` | Run now |
| `GET /api/runs/latest` | Status |
| `POST /hooks/wake` | Scheduled wake (bearer `CINDER_WAKE_TOKEN`); streams heartbeat lines until the run finishes |
| `GET /healthz` | Liveness (no internals) |

## 8. Scheduling on a Sprite

Sprites pause when idle and have no cron, so the run is started from outside:
- **GitHub Actions workflow** in this repo, `schedule: cron: "0 10 * * *"` (10:00 UTC = 4 am CST / 5 am CDT, leaving slack for Actions' scheduling delays). It calls `POST https://<sprite-url>/hooks/wake` with a secret token and **keeps the request open** while Cinder streams heartbeats, so the Sprite stays awake for the whole run (Sprites stay awake while serving HTTP requests). Job timeout: 60 min.
- **Catch-up**: whenever the app is opened or woken, if today's run hasn't succeeded and it's past the generation time, start one.
- Optionally a second, later Actions cron as a retry.

## 9. Agent invocation (claude CLI)

Measured on this Sprite: by default, `claude -p` loads every claude.ai connector (hundreds of MCP tools), so a trivial call cost **$2.15** of usage. With connectors shut out it cost **$0.035**. Every call must therefore use:

```
claude -p <prompt>
  --output-format json
  --json-schema <schema>            # structured output → result.structured_output
  --tools "<explicit list>"         # e.g. "WebSearch,WebFetch,Read,Glob,Grep" for ideation; "" for profile
  --allowedTools "<same list>"
  --permission-prompts none         # anything else is auto-denied
  --strict-mcp-config --mcp-config <empty {"mcpServers":{}} file>
  --setting-sources project         # skip user hooks/settings (to verify: auth still works)
  --no-session-persistence
  --max-budget-usd <cap>            # per call; defaults below
```
- Run with `cwd` = the run's work directory (digests only), never the repo or `$HOME`.
- Don't use `--bare`: it drops subscription (OAuth) auth.
- No Bash, Edit or Write tools for any agent call; Cinder's own code does all GitHub writes.
- `--allowedTools` pre-approves `Read(./**)`, never a bare `Read`: a bare rule approves reads of any path (such as `~/.cinder/env`). Reads outside the work dir would need a permission prompt, which `--permission-prompts none` denies.
- Default budget caps (configurable): ideation $5, profile $0.50, spec $3, never-rule $0.20. Record `total_cost_usd` per call.
- Timeouts: ideation 30 min, spec 15 min. Kill and mark failed on timeout.
- Fallback: if the subscription CLI is unavailable, `ANTHROPIC_API_KEY` (via the Sprite's Anthropic gateway connection) can be used with the same flags.

## 10. Auth & security
- Sprite URL set to **public**; Cinder enforces all auth itself.
- **Owner login**: GitHub OAuth app; only `CINDER_OWNER_LOGIN` may sign in. Signed, `HttpOnly`, `Secure`, `SameSite=Lax` session cookie (30 days). Fallback if OAuth isn't configured yet: a one-time access code generated into `~/.cinder/env`.
- **Write protection**: state-changing endpoints require the session cookie + JSON body + matching `Origin` header.
- **Wake endpoint**: bearer token, constant-time compare, rate-limited; it can only start a run.
- **Untrusted content**: repo contents and web pages may contain prompt injection. Agents get read-only tools in a sandbox work dir; outputs are validated against the JSON schema; the UI renders all card/spec text as plain text (no raw HTML), and links get `rel="noopener noreferrer"`.
- No endpoint exposes env vars, file paths, logs with secrets, or stack traces. Secrets live only in `~/.cinder/env`.

## 11. Configuration (`~/.cinder/env`)
| Variable | Purpose |
|---|---|
| `CINDER_BASE_URL` | e.g. `https://hacksgiving-b6x4r.sprites.app` |
| `CINDER_GITHUB_MODE` | `gateway` (Sprite API gateway, no token) or `token` |
| `GITHUB_TOKEN` | Only if mode is `token` (fine-grained PAT) |
| `CINDER_HOME_REPO` | `andrice90/cinder` (default) |
| `CINDER_OWNER_LOGIN` | GitHub username allowed to log in |
| `GITHUB_OAUTH_CLIENT_ID` / `GITHUB_OAUTH_CLIENT_SECRET` | Login OAuth app |
| `CINDER_SESSION_SECRET` | Cookie signing (auto-generated) |
| `CINDER_WAKE_TOKEN` | Shared with the GitHub Actions secret (auto-generated) |
| `CINDER_NOTIFY_EMAIL` | Where the morning email goes |
| `CINDER_AGENTMAIL_INBOX` | Sending inbox. If unset, the inbox the gateway key is scoped to (the current key is limited to one inbox, so Cinder can't create its own) |
| `CINDER_TZ` / `CINDER_READY_BY` | `America/Chicago` / `07:00` |
| `CINDER_CLAUDE_BIN` | Path to `claude` (tests point this at a fake) |

## 12. Setup the owner must do
1. **GitHub API access for all repos.** The SSH key on this Sprite (`~/.ssh/id_ed25519_fly_agent`) looks like a **deploy key, which covers only this one repo and can't use the API**. Pick one:
   - connect GitHub in the Sprite API gateway (`curl -s https://api.sprites.dev/v1/gateway/list` shows it as available, not connected), with read access to contents/metadata/issues and write access to contents + pull requests; **or**
   - create a fine-grained PAT with the same permissions on all repos and put it in `~/.cinder/env`.
2. Create a **GitHub OAuth app** (callback `https://<sprite-url>/auth/callback`) and add the client ID/secret.
3. Make the Sprite URL public: `sprite config update --url-auth public` (from a machine where the `sprite` CLI is logged in).
4. Add the repo secret `CINDER_WAKE_TOKEN` (and `CINDER_WAKE_URL`) for the Actions workflow.
5. Set `CINDER_NOTIFY_EMAIL`.
6. ~~Rename the repo to `cinder`~~ (done).

## 13. Environment notes / cleanup
- A demo MCP server is still running as Sprite service `mcp-demo` on port 8080 (code in `~/mcp-demo/`). Remove it before installing Cinder: `sprite-env services delete mcp-demo` (or equivalent), then `rm -rf ~/mcp-demo`.
- The remote repo is **empty** (no commits on `main`). The first push needs a bootstrap commit on `main` before feature-branch PRs are possible.
- The Python MCP library is now at 2.x (`FastMCP` renamed `MCPServer`); not needed by Cinder, noted for future MCP work.
- Unverified: whether a Sprite stays awake for a long background subprocess without an open HTTP request. The wake design (§8) avoids depending on it.

## 14. Build milestones
1. **Skeleton**: package layout, SQLite schema, settings/env loading, Sprite service, `/healthz`, access-code login.
2. **Deck UI**: swipe stack, notes sheet, undo, never-rule toast, saved/history/settings pages, seeded with fixture cards.
3. **GitHub + digests**: repo sync, digests, exclusion toggles.
4. **Agent wrapper**: CLI flags per §9, schema validation, cost/time caps; fake-claude test binary.
5. **Daily run**: profile update, slots, ideation, ordering, run records, Run now.
6. **Specs**: worker, spec prompt, branch + file + PR via API, status in Saved.
7. **Scheduling & notify**: wake endpoint with heartbeat streaming, catch-up, Actions workflow, AgentMail email.
8. **GitHub OAuth login**, security pass, PWA polish.
9. **Real end-to-end run** on the owner's repos; tune prompts.

## 15. Later (not v1)
- Paid SEO/keyword data (DataForSEO, Semrush) and search APIs (Exa, Tavily, Firecrawl via the Sprite gateway).
- Promote a project idea to a new repo.
- Create GitHub issues from a spec's task breakdown.
- Multiple users.
