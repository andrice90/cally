# Cinder

A personal agent that reads your GitHub repos and, every morning, deals you a deck of up to 10 researched
idea cards: new features for your projects and new projects that build on them. Swipe right to get a full
spec opened as a PR, left to pass, up to add a note. Your swipes teach it your taste.

Full design: [`docs/SPEC.md`](docs/SPEC.md).

## Run locally

```bash
uv sync
uv run python -m cinder seed-demo   # optional: demo cards for the UI
uv run python -m cinder info        # shows the login access code
uv run python -m cinder serve --port 8080
```

Runtime data and secrets live in `~/.cinder/` (`cinder.db`, `env`, `runs/`). Missing secrets (session key,
wake token, access code) are generated into `~/.cinder/env` on first start.

## Tests

```bash
uv run pytest
```

Tests use a fake `claude` binary (`tests/fake_claude.py`), an in-memory GitHub API and a fake AgentMail.

## Deploy on the Sprite

1. Free port 8080 (`sprite-env services delete mcp-demo`), then `scripts/install-service.sh`.
2. Connect GitHub in the Sprite API gateway (or set `CINDER_GITHUB_MODE=token` and `GITHUB_TOKEN`).
3. Set `CINDER_BASE_URL`, `CINDER_NOTIFY_EMAIL` and, for GitHub login, `CINDER_OWNER_LOGIN`,
   `GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET` in `~/.cinder/env`, then
   `sprite-env services restart cinder`.
4. Add repo secrets `CINDER_WAKE_URL` (the Sprite URL) and `CINDER_WAKE_TOKEN` (from `~/.cinder/env`)
   for `.github/workflows/cinder-wake.yml`.
