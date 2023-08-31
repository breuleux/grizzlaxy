import argparse
import importlib
import json
import sys

import uvicorn
from authlib.integrations.starlette_client import OAuth
from starlette.applications import Starlette
from starlette.config import Config
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.sessions import SessionMiddleware

from .auth import OAuthMiddleware, PermissionDict
from .find import collect_routes, collect_routes_from_module, compile_routes


def main(argv=None):
    if argv is None:
        argv = sys.argv

    parser = argparse.ArgumentParser(description="Start a grizzlaxy of starbears.")

    parser.add_argument(
        "root", nargs="?", metavar="ROOT", help="Directory or script", default=None
    )
    parser.add_argument(
        "--module", "-m", metavar="MODULE", help="Directory or script", default=None
    )
    parser.add_argument("--port", type=int, help="Port to serve on", default=8000)
    parser.add_argument("--host", type=str, help="Hostname", default="127.0.0.1")
    parser.add_argument(
        "--permissions", type=str, help="Permissions file", default=None
    )
    parser.add_argument("--secrets", type=str, help="Secrets file", default=None)
    parser.add_argument("--ssl-keyfile", type=str, help="SSL key file", default=None)
    parser.add_argument(
        "--ssl-certfile", type=str, help="SSL certificate file", default=None
    )
    parser.add_argument(
        "--hot", action="store_true", help="Automatically hot-reload the code"
    )

    options = parser.parse_args(argv[1:])

    if not options.root and not options.module:
        exit("MISSING ARGUMENT: Either the ROOT argument or -m MODULE must be used")

    if options.hot:
        import jurigged

        jurigged.watch(options.root)

    if options.root:
        collected = collect_routes(options.root)
    elif options.module:
        collected = collect_routes_from_module(importlib.import_module(options.module))

    routes = compile_routes("/", collected)

    app = Starlette(routes=routes)

    if options.ssl_keyfile:
        # This doesn't seem to do anything?
        app.add_middleware(HTTPSRedirectMiddleware)

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
            is_authorized=PermissionDict(json.load(open(options.permissions))),
        )
        app.add_middleware(SessionMiddleware, secret_key="!secret")

    app.map = collected

    uvicorn.run(
        app,
        host=options.host,
        port=options.port,
        log_level="info",
        ssl_keyfile=options.ssl_keyfile,
        ssl_certfile=options.ssl_certfile,
    )
