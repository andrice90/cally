"""GitHub REST client: via the Sprite API gateway (no token) or a personal access token."""

from __future__ import annotations

import base64
import logging

import httpx

log = logging.getLogger("cally.github")

GATEWAY_LIST_URL = "https://api.sprites.dev/v1/gateway/list"
PUBLIC_API = "https://api.github.com"


class GitHubError(RuntimeError):
    pass


class GitHubNotConfigured(GitHubError):
    pass


async def discover_gateway_url(client: httpx.AsyncClient | None = None) -> str:
    """Find the GitHub connection's gateway_base_url from the Sprite gateway list."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=20)
    try:
        resp = await client.get(GATEWAY_LIST_URL)
        resp.raise_for_status()
        for conn in resp.json().get("connections", []):
            if conn.get("provider") == "github" and conn.get("gateway_base_url"):
                return conn["gateway_base_url"].rstrip("/")
    except httpx.HTTPError as exc:
        raise GitHubNotConfigured(f"could not read the Sprite gateway list: {exc}") from exc
    finally:
        if own:
            await client.aclose()
    raise GitHubNotConfigured(
        "GitHub is not connected in the Sprite API gateway (or set CALLY_GITHUB_MODE=token)"
    )


class GitHub:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    @classmethod
    async def create(cls, cfg, transport: httpx.AsyncBaseTransport | None = None) -> "GitHub":
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "cally",
        }
        if cfg.github_api_url:
            base = cfg.github_api_url
        elif cfg.github_mode == "token":
            base = PUBLIC_API
        else:
            base = await discover_gateway_url()
        if cfg.github_mode == "token":
            if not cfg.github_token:
                raise GitHubNotConfigured("CALLY_GITHUB_MODE=token but GITHUB_TOKEN is not set")
            headers["Authorization"] = f"Bearer {cfg.github_token}"
        client = httpx.AsyncClient(
            base_url=base, headers=headers, timeout=30, transport=transport, follow_redirects=True
        )
        return cls(client)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def _req(self, method: str, path: str, ok404: bool = False, **kw):
        resp = await self.client.request(method, path, **kw)
        if ok404 and resp.status_code in (404, 409):  # 409: empty repository
            return None
        if resp.status_code >= 400:
            msg = ""
            try:
                msg = resp.json().get("message", "")
            except ValueError:
                pass
            raise GitHubError(f"GitHub {method} {path} -> {resp.status_code} {msg}".strip())
        return resp.json() if resp.content else None

    async def _paged(self, path: str, params: dict, key: str | None = None, limit: int = 1000):
        out: list = []
        page = 1
        while len(out) < limit:
            data = await self._req("GET", path, params={**params, "per_page": 100, "page": page})
            items = data.get(key, []) if key else data
            out.extend(items)
            if len(items) < 100:
                break
            page += 1
        return out[:limit]

    # ---- reads ----
    async def list_repos(self) -> list[dict]:
        try:
            return await self._paged(
                "/user/repos",
                {"affiliation": "owner,collaborator,organization_member", "sort": "pushed"},
            )
        except GitHubError as exc:
            log.info("user/repos failed (%s); trying installation/repositories", exc)
            return await self._paged("/installation/repositories", {}, key="repositories")

    async def readme(self, full_name: str) -> str:
        data = await self._req("GET", f"/repos/{full_name}/readme", ok404=True)
        return _decode(data) if data else ""

    async def contents(self, full_name: str, path: str = "", ref: str | None = None):
        params = {"ref": ref} if ref else {}
        return await self._req("GET", f"/repos/{full_name}/contents/{path}", ok404=True, params=params)

    async def file_text(self, full_name: str, path: str, ref: str | None = None) -> str | None:
        data = await self.contents(full_name, path, ref)
        if not data or isinstance(data, list):
            return None
        return _decode(data)

    async def tree(self, full_name: str, ref: str) -> list[str]:
        data = await self._req(
            "GET", f"/repos/{full_name}/git/trees/{ref}", ok404=True, params={"recursive": "1"}
        )
        if not data:
            return []
        return [t["path"] for t in data.get("tree", []) if t.get("type") == "blob"]

    async def commits(self, full_name: str, n: int = 20) -> list[str]:
        data = await self._req("GET", f"/repos/{full_name}/commits", ok404=True, params={"per_page": n})
        return [c["commit"]["message"].splitlines()[0] for c in (data or []) if c.get("commit")]

    async def issues(self, full_name: str, n: int = 20) -> list[str]:
        data = await self._req(
            "GET", f"/repos/{full_name}/issues", ok404=True, params={"state": "open", "per_page": n}
        )
        return [i["title"] for i in (data or []) if "pull_request" not in i]

    async def languages(self, full_name: str) -> list[str]:
        data = await self._req("GET", f"/repos/{full_name}/languages", ok404=True)
        return list((data or {}).keys())

    async def repo(self, full_name: str) -> dict:
        return await self._req("GET", f"/repos/{full_name}")

    # ---- writes ----
    async def open_spec_pr(
        self, full_name: str, branch: str, path: str, content: str, title: str, body: str
    ) -> str:
        """Create a branch off the default branch, add one file, and open a PR. Returns the PR URL."""
        repo = await self.repo(full_name)
        base = repo["default_branch"]
        ref = await self._req("GET", f"/repos/{full_name}/git/ref/heads/{base}", ok404=True)
        if not ref:
            raise GitHubError(f"{full_name} has no commits on {base}; push a first commit before specs")
        sha = ref["object"]["sha"]
        existing = await self._req("GET", f"/repos/{full_name}/git/ref/heads/{branch}", ok404=True)
        if not existing:
            await self._req(
                "POST", f"/repos/{full_name}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": sha}
            )
        put: dict = {
            "message": title,
            "content": base64.b64encode(content.encode()).decode(),
            "branch": branch,
        }
        current = await self.contents(full_name, path, ref=branch)
        if isinstance(current, dict) and current.get("sha"):
            put["sha"] = current["sha"]
        await self._req("PUT", f"/repos/{full_name}/contents/{path}", json=put)
        owner = full_name.split("/")[0]
        pulls = await self._req(
            "GET", f"/repos/{full_name}/pulls", params={"head": f"{owner}:{branch}", "state": "open"}
        )
        if pulls:
            return pulls[0]["html_url"]
        pr = await self._req(
            "POST",
            f"/repos/{full_name}/pulls",
            json={"title": title, "head": branch, "base": base, "body": body},
        )
        return pr["html_url"]


def _decode(data: dict) -> str:
    if data.get("encoding") == "base64":
        return base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
    return data.get("content", "") or ""
