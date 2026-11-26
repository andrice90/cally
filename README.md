# Cally

A personal agent that reads your GitHub repos and, every morning, deals you a deck of up to 10 researched
idea cards: new features for your projects and new projects that build on them. Swipe right to get a full
spec opened as a PR, left to pass, up to add a note. Your swipes teach it your taste.

Full design: [`docs/SPEC.md`](docs/SPEC.md). Built for Fly.io Hacksgiving 2026.

## How it runs on a Sprite

- **Agent:** the `claude` CLI in print mode, with read-only tools and web search, confined to a per-run work dir.
- **Sprites connector:** AgentMail sends the daily summary email (what's waiting, yesterday's new specs, yesterday's activity).
- **Sprite service:** one FastAPI process on port 8080 serves the swipe app and a wake hook that a GitHub Actions cron calls each morning.
- **GitHub:** a fine-grained token reads repos and opens spec PRs.

## Run locally

```bash
uv sync
uv run python -m cally seed-demo   # optional: demo cards for the UI
uv run python -m cally info        # shows the login access code
uv run python -m cally serve --port 8080
```

Runtime data and secrets live in `~/.cally/` (`cally.db`, `env`, `runs/`). Missing secrets (session key,
wake token, access code) are generated into `~/.cally/env` on first start.

## Tests

```bash
uv run pytest
```

Tests use a fake `claude` binary (`tests/fake_claude.py`), an in-memory GitHub API and a fake AgentMail.

## Deploy on the Sprite

1. Free port 8080 (`sprite-env services delete mcp-demo`), then `scripts/install-service.sh`.
2. Connect GitHub in the Sprite API gateway (or set `CALLY_GITHUB_MODE=token` and `GITHUB_TOKEN`).
3. Set `CALLY_BASE_URL`, `CALLY_NOTIFY_EMAIL` and, for GitHub login, `CALLY_OWNER_LOGIN`,
   `GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET` in `~/.cally/env`, then
   `sprite-env services restart cally`.
4. Add repo secrets `CALLY_WAKE_URL` (the Sprite URL) and `CALLY_WAKE_TOKEN` (from `~/.cally/env`)
   for `.github/workflows/cally-wake.yml`.

## License

Cally is open source under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE).
