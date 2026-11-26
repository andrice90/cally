"""Morning email via AgentMail through the Sprite API gateway."""

from __future__ import annotations

import logging

import httpx

from .github import GATEWAY_LIST_URL

log = logging.getLogger("cally.notify")


class NotifyError(RuntimeError):
    pass


class Notifier:
    def __init__(self, cfg, transport: httpx.AsyncBaseTransport | None = None):
        self.cfg = cfg
        self.transport = transport

    async def _base(self, client: httpx.AsyncClient) -> str:
        if self.cfg.agentmail_url:
            return self.cfg.agentmail_url
        resp = await client.get(GATEWAY_LIST_URL)
        resp.raise_for_status()
        for conn in resp.json().get("connections", []):
            if conn.get("provider") == "agentmail" and conn.get("gateway_base_url"):
                return conn["gateway_base_url"].rstrip("/")
        raise NotifyError("AgentMail is not connected in the Sprite API gateway")

    async def _inbox(self, client: httpx.AsyncClient, base: str) -> str:
        if self.cfg.agentmail_inbox:
            return self.cfg.agentmail_inbox
        me = (await client.get(f"{base}/v0/auth/me")).json()
        if me.get("inbox_id"):
            return me["inbox_id"]
        inboxes = (await client.get(f"{base}/v0/inboxes")).json().get("inboxes", [])
        if not inboxes:
            raise NotifyError("no AgentMail inbox available; set CALLY_AGENTMAIL_INBOX")
        return inboxes[0]["inbox_id"]

    async def send(self, subject: str, text: str, html: str | None = None, to: str | None = None,
                   attachments: list[dict] | None = None) -> bool:
        to = to or self.cfg.notify_email
        if not to:
            log.info("no recipient set; skipping email")
            return False
        async with httpx.AsyncClient(timeout=30, transport=self.transport) as client:
            base = await self._base(client)
            inbox = await self._inbox(client, base)
            resp = await client.post(
                f"{base}/v0/inboxes/{inbox}/messages/send",
                json={"to": [to], "subject": subject, "text": text, **({"html": html} if html else {}),
                      **({"attachments": attachments} if attachments else {})},
            )
            if resp.status_code >= 400:
                raise NotifyError(f"AgentMail send failed: {resp.status_code}")
        return True
