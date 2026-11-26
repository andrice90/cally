"""Repo sync and per-repo digests (cached on pushed_at)."""

from __future__ import annotations

import logging

from .db import DB, now
from .github import GitHub

log = logging.getLogger("cally.digest")

MANIFESTS = (
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "Cargo.toml",
    "go.mod",
    "Gemfile",
    "composer.json",
    "pubspec.yaml",
    "build.gradle",
    "pom.xml",
    "Package.swift",
    "deno.json",
    "app.json",
)
DIGEST_MAX = 4000


async def sync_repos(db: DB, gh: GitHub) -> int:
    repos = await gh.list_repos()
    with db.tx() as c:
        for r in repos:
            default_excluded = 1 if (r.get("archived") or r.get("fork")) else 0
            c.execute(
                """INSERT INTO repos(id, full_name, description, default_branch, pushed_at, archived, fork,
                                     private, excluded, synced_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET full_name=excluded.full_name,
                     description=excluded.description, default_branch=excluded.default_branch,
                     pushed_at=excluded.pushed_at, archived=excluded.archived, fork=excluded.fork,
                     private=excluded.private, synced_at=excluded.synced_at,
                     excluded=CASE WHEN repos.excluded_set THEN repos.excluded ELSE excluded.excluded END""",
                (
                    r["id"],
                    r["full_name"],
                    r.get("description") or "",
                    r.get("default_branch") or "main",
                    r.get("pushed_at") or "",
                    int(bool(r.get("archived"))),
                    int(bool(r.get("fork"))),
                    int(bool(r.get("private"))),
                    default_excluded,
                    now(),
                ),
            )
        ids = [r["id"] for r in repos]
        if ids:
            c.execute(
                f"DELETE FROM repos WHERE id NOT IN ({','.join('?' * len(ids))})", tuple(ids)
            )
    return len(repos)


def _clip(text: str, n: int) -> str:
    text = text.strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


async def build_digest(gh: GitHub, repo: dict, meta: dict | None = None) -> str:
    name = repo["full_name"]
    meta = meta or await gh.repo(name)
    branch = repo.get("default_branch") or meta.get("default_branch") or "main"
    langs = await gh.languages(name)
    files = await gh.tree(name, branch)
    top = sorted({f.split("/")[0] + ("/" if "/" in f else "") for f in files})
    commits = await gh.commits(name)
    issues = await gh.issues(name)
    readme = await gh.readme(name)

    manifests: list[str] = []
    for m in MANIFESTS:
        if m in files:
            text = await gh.file_text(name, m, ref=branch)
            if text:
                manifests.append(f"--- {m}\n{_clip(text, 600)}")
        if len(manifests) >= 2:
            break

    head = [
        f"# {name}",
        f"Description: {meta.get('description') or repo.get('description') or '-'}",
        f"Topics: {', '.join(meta.get('topics') or []) or '-'}",
        f"Languages: {', '.join(langs) or '-'}",
        f"Stars: {meta.get('stargazers_count', 0)} · Last push: {repo.get('pushed_at') or '-'}"
        f" · {'private' if repo.get('private') else 'public'}",
        f"Files ({len(files)}): {_clip(' '.join(top), 500) or '(empty)'}",
    ]
    if commits:
        head.append("Recent commits:\n" + "\n".join(f"- {_clip(c, 100)}" for c in commits[:20]))
    if issues:
        head.append("Open issues:\n" + "\n".join(f"- {_clip(i, 100)}" for i in issues[:20]))
    body = "\n".join(head)
    if manifests:
        body += "\n" + "\n".join(manifests)
    room = DIGEST_MAX - len(body) - 20
    if readme and room > 200:
        body += "\n--- README\n" + _clip(readme, room)
    return _clip(body, DIGEST_MAX)


async def refresh_digests(db: DB, gh: GitHub, max_repos: int) -> list[dict]:
    """Rebuild stale digests for the most recently pushed included repos; return those repos."""
    repos = db.all(
        "SELECT * FROM repos WHERE excluded=0 ORDER BY pushed_at DESC LIMIT ?", (max_repos,)
    )
    out = []
    for r in repos:
        if r["digest"] and r["digest_pushed_at"] == r["pushed_at"]:
            out.append(r)
            continue
        try:
            digest = await build_digest(gh, r)
        except Exception as exc:  # one bad repo shouldn't sink the run
            log.warning("digest failed for %s: %s", r["full_name"], exc)
            if r["digest"]:
                out.append(r)
            continue
        db.run(
            "UPDATE repos SET digest=?, digest_pushed_at=? WHERE id=?",
            (digest, r["pushed_at"], r["id"]),
        )
        r["digest"] = digest
        out.append(r)
    return out
