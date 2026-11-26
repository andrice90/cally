"""Configuration: loads ~/.cinder/env and generates missing secrets."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

GENERATED = ("CINDER_SESSION_SECRET", "CINDER_WAKE_TOKEN", "CINDER_ACCESS_CODE")


def cinder_home() -> Path:
    return Path(os.environ.get("CINDER_HOME", Path.home() / ".cinder"))


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
        lines = [f"{k}={secrets.token_urlsafe(32 if k != 'CINDER_ACCESS_CODE' else 12)}" for k in missing]
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

    @property
    def db_path(self) -> Path:
        return self.home / "cinder.db"

    @property
    def runs_dir(self) -> Path:
        return self.home / "runs"

    @property
    def oauth_enabled(self) -> bool:
        return bool(self.oauth_client_id and self.oauth_client_secret and self.owner_login)


def load_config() -> Config:
    home = cinder_home()
    file_values = load_env_file(home)

    def get(key: str, default: str = "") -> str:
        return os.environ.get(key) or file_values.get(key) or default

    return Config(
        home=home,
        base_url=get("CINDER_BASE_URL", "http://localhost:8080").rstrip("/"),
        github_mode=get("CINDER_GITHUB_MODE", "gateway"),
        github_token=get("GITHUB_TOKEN"),
        github_api_url=get("CINDER_GITHUB_API_URL").rstrip("/"),
        home_repo=get("CINDER_HOME_REPO", "andrice90/cinder"),
        owner_login=get("CINDER_OWNER_LOGIN"),
        oauth_client_id=get("GITHUB_OAUTH_CLIENT_ID"),
        oauth_client_secret=get("GITHUB_OAUTH_CLIENT_SECRET"),
        session_secret=get("CINDER_SESSION_SECRET"),
        wake_token=get("CINDER_WAKE_TOKEN"),
        access_code=get("CINDER_ACCESS_CODE"),
        notify_email=get("CINDER_NOTIFY_EMAIL"),
        agentmail_inbox=get("CINDER_AGENTMAIL_INBOX"),
        agentmail_url=get("CINDER_AGENTMAIL_URL").rstrip("/"),
        tz=get("CINDER_TZ", "America/Chicago"),
        ready_by=get("CINDER_READY_BY", "07:00"),
        claude_bin=get("CINDER_CLAUDE_BIN", "claude"),
        scheduler=get("CINDER_SCHEDULER", "1") == "1",
    )
