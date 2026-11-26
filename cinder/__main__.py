"""python -m cinder [serve|seed-demo|info]"""

from __future__ import annotations

import argparse
import logging


def main() -> None:
    p = argparse.ArgumentParser(prog="cinder")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="run the web app")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8080)
    sub.add_parser("seed-demo", help="add fixture cards to the deck (development)")
    sub.add_parser("info", help="show config status and the login access code")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    from .config import load_config
    cfg = load_config()

    if args.cmd in (None, "serve"):
        import uvicorn
        from .app import create_app
        uvicorn.run(create_app(cfg), host=getattr(args, "host", "0.0.0.0"), port=getattr(args, "port", 8080),
                    proxy_headers=True, forwarded_allow_ips="*", log_level="info")
    elif args.cmd == "seed-demo":
        from .db import DB
        from .fixtures import seed
        print(f"added {seed(DB(cfg.db_path))} demo cards")
    elif args.cmd == "info":
        print(f"home:         {cfg.home}")
        print(f"base url:     {cfg.base_url}")
        print(f"github mode:  {cfg.github_mode}")
        print(f"login:        {'GitHub OAuth (' + cfg.owner_login + ')' if cfg.oauth_enabled else 'access code'}")
        if not cfg.oauth_enabled:
            print(f"access code:  {cfg.access_code}")
        print(f"notify email: {cfg.notify_email or '(not set)'}")


if __name__ == "__main__":
    main()
