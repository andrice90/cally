"""Configuration: loads ~/.cally/env and generates missing secrets."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

GENERATED = ("CALLY_SESSION_SECRET", "CALLY_WAKE_TOKEN", "CALLY_ACCESS_CODE")


def cally_home() -> Path:
    return Path(os.environ.get("CALLY_HOME", Path.home() / ".cally"))


def _parse_env(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        out[key.strip()] = value
    return out


def load_env_file(home: Path) -> dict[str, str]:
    """Read the env file, appending any generated secrets that are missing."""
    home.mkdir(parents=True, exist_ok=True)
    os.chmod(home, 0o700)
    path = home / "env"
    values = _parse_env(path.read_text()) if path.exists() else {}
    missing = [k for k in GENERATED if not values.get(k)]
    if missing:
        lines = [f"{k}={secrets.token_urlsafe(32 if k != 'CALLY_ACCESS_CODE' else 12)}" for k in missing]
        with path.open("a") as fh:
            if path.stat().st_size and not path.read_text().endswith("\n"):
                fh.write("\n")
            fh.write("\n".join(lines) + "\n")
        values.update(_parse_env("\n".join(lines)))
    os.chmod(path, 0o600)
    return values


@dataclass
class Config:
    home: Path
    base_url: str
    github_mode: str  # gateway | token | fake
    github_token: str
    github_api_url: str
    home_repo: str
    owner_login: str
    oauth_client_id: str
    oauth_client_secret: str
    session_secret: str
    wake_token: str
    access_code: str
    notify_email: str
    agentmail_inbox: str
    agentmail_url: str
    tz: str
    ready_by: str
    claude_bin: str
    scheduler: bool
    spec_grace: int  # seconds a saved card waits before its spec starts, so undo still works

    @property
    def db_path(self) -> Path:
        return self.home / "cally.db"

    @property
    def runs_dir(self) -> Path:
        return self.home / "runs"

    @property
    def oauth_enabled(self) -> bool:
        return bool(self.oauth_client_id and self.oauth_client_secret and self.owner_login)


def load_config() -> Config:
    home = cally_home()
    file_values = load_env_file(home)

    def get(key: str, default: str = "") -> str:
        return os.environ.get(key) or file_values.get(key) or default

    return Config(
        home=home,
        base_url=get("CALLY_BASE_URL", "http://localhost:8080").rstrip("/"),
        github_mode=get("CALLY_GITHUB_MODE", "gateway"),
        github_token=get("GITHUB_TOKEN"),
        github_api_url=get("CALLY_GITHUB_API_URL").rstrip("/"),
        home_repo=get("CALLY_HOME_REPO", "andrice90/cally"),
        owner_login=get("CALLY_OWNER_LOGIN"),
        oauth_client_id=get("GITHUB_OAUTH_CLIENT_ID"),
        oauth_client_secret=get("GITHUB_OAUTH_CLIENT_SECRET"),
        session_secret=get("CALLY_SESSION_SECRET"),
        wake_token=get("CALLY_WAKE_TOKEN"),
        access_code=get("CALLY_ACCESS_CODE"),
        notify_email=get("CALLY_NOTIFY_EMAIL"),
        agentmail_inbox=get("CALLY_AGENTMAIL_INBOX"),
        agentmail_url=get("CALLY_AGENTMAIL_URL").rstrip("/"),
        tz=get("CALLY_TZ", "America/Chicago"),
        ready_by=get("CALLY_READY_BY", "07:00"),
        claude_bin=get("CALLY_CLAUDE_BIN", "claude"),
        scheduler=get("CALLY_SCHEDULER", "1") == "1",
        spec_grace=int(get("CALLY_SPEC_GRACE", "30")),
    )
