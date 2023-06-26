import argparse
import json
import sys

import uvicorn
from authlib.integrations.starlette_client import OAuth
from starlette.applications import Starlette
from starlette.config import Config
from starlette.middleware.sessions import SessionMiddleware

from .auth import OAuthMiddleware
from .find import collect_routes, compile_routes


def main(argv=None):
    if argv is None:
        argv = sys.argv

    parser = argparse.ArgumentParser(description="Start a grizzlaxy of starbears.")

    parser.add_argument("root", metavar="ROOT", help="Directory or script")
    parser.add_argument("--port", type=int, help="Port to serve on", default=8000)
    parser.add_argument("--host", type=str, help="Hostname", default="127.0.0.1")
    parser.add_argument(
        "--permissions", type=str, help="Permissions file", default=None
    )
    parser.add_argument("--secrets", type=str, help="Secrets file", default=None)

    options = parser.parse_args(argv[1:])

    collected = collect_routes(options.root)
    routes = compile_routes("/", collected)

    app = Starlette(routes=[routes])

    if options.secrets:
        config = Config(options.secrets)
        oauth = OAuth(config)

        CONF_URL = "https://accounts.google.com/.well-known/openid-configuration"
        oauth.register(
            name="google",
            server_metadata_url=CONF_URL,
            client_kwargs={
                "scope": "openid email profile",
                "prompt": "select_account",
            },
        )
        app.add_middleware(
            OAuthMiddleware,
            oauth=oauth,
            permissions=json.load(open(options.permissions)),
        )
        app.add_middleware(SessionMiddleware, secret_key="!secret")

    app.map = collected

    uvicorn.run(app, host=options.host, port=options.port, log_level="info")
